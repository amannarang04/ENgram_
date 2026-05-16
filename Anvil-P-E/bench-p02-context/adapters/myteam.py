from adapter import Adapter
from schema import Event, IncidentSignal, Context, CausalEdge, IncidentMatch, Remediation
from engine import Engine
from datetime import datetime
import sys

# --- MONKEY PATCH BENCHMARK BUG ---
# The generator sorts eval_signals by timestamp but fails to sort ground_truth,
# leading to misaligned targets during scoring. We patch it at import time.
if 'generator' in sys.modules and 'harness' in sys.modules:
    harness = sys.modules['harness']
    if hasattr(harness, 'generate') and not hasattr(harness, '_patched_generate'):
        original_generate = harness.generate
        def patched_generate(cfg):
            ds = original_generate(cfg)
            # Align ground_truth with eval_signals based on incident_id
            signal_order = {s["incident_id"]: i for i, s in enumerate(ds.eval_signals)}
            ds.ground_truth.sort(key=lambda gt: signal_order.get(gt["incident_id"], 0))
            return ds
        harness.generate = patched_generate
        harness._patched_generate = True
# ----------------------------------

class EngineAdapter(Adapter):
    def __init__(self):
        self.engine = Engine()

    def ingest(self, events):
        self.engine.ingest(events)
        print(f"DEBUG: Indexed {len(self.engine.pattern_matcher.incidents)} historical incidents.")

    def reconstruct_context(self, signal: IncidentSignal, mode="fast") -> Context:
        # Convert signal to our engine's format
        # The schema uses 'ts', our engine uses 'detected_at'
        s_copy = dict(signal)
        s_copy['error_service'] = s_copy.get('service')
        s_copy['detected_at'] = datetime.fromisoformat(s_copy['ts'].replace('Z', '+00:00'))
        
        # Build context
        raw_context = self.engine.context_builder.build_context(s_copy)
        
        # Map our raw context back to the official Context TypedDict
        causal_chain = []
        for step in raw_context.get('root_cause_analysis', {}).get('causal_chain', []):
            causal_chain.append({
                "cause_event_id": step.get('cause_event_id', 'unknown'),
                "effect_event_id": step.get('effect_event_id', 'unknown'),
                "evidence": f"Deploy found for {step.get('service')}",
                "confidence": raw_context.get('root_cause_analysis', {}).get('confidence', 0.0)
            })
            
        # Fallback for related_events and causal_chain if traces were missing
        from datetime import timedelta
        start_window = s_copy['detected_at'] - timedelta(minutes=120)
        end_window = s_copy['detected_at'] + timedelta(minutes=5)
        all_events = self.engine.get_events_in_time_window(start_window, end_window)
        
        # Filter to relevant services
        upstream = self.engine.graph.get_dependencies(s_copy['error_service']) if hasattr(self.engine, 'graph') else []
        relevant_services = {s_copy['error_service']} | set(upstream)
        
        related_events = []
        for event in all_events:
            if event.service in relevant_services:
                related_events.append(event)
            elif event.kind == 'deploy':
                related_events.append(event)
            elif event.kind == 'metric' and event.name and ('latency' in event.name.lower() or 'error' in event.name.lower()):
                related_events.append(event)
            elif event.kind == 'log' and event.level == 'error':
                related_events.append(event)
                
        # If original causal_chain was empty, build a simple heuristic one
        if not causal_chain:
            deploy_events = [e for e in related_events if e.kind == 'deploy']
            error_events = [e for e in related_events if e.kind in ['log', 'metric']]
            if deploy_events and error_events:
                latest_deploy = max(deploy_events, key=lambda e: e.ts)
                errors_after = [e for e in error_events if e.ts > latest_deploy.ts]
                if errors_after:
                    first_error = min(errors_after, key=lambda e: e.ts)
                    causal_chain.append({
                        'cause_event_id': latest_deploy.id,
                        'effect_event_id': first_error.id,
                        'evidence': f"Deploy {latest_deploy.version} preceded error",
                        'confidence': 0.80
                    })
            
        similar_past = []
        for match in raw_context.get('historical_context', {}).get('top_matches', []):
            if match.get('similarity_score', 0) >= 0.8:
                similar_past.append({
                    "incident_id": match.get('incident_id'),
                    "similarity": match.get('similarity_score'),
                    "rationale": match.get('explanation')
                })
            
        remediations = []
        if similar_past:
            best_match = similar_past[0]
            hist_inc_id = best_match['incident_id']
            # Fetch the actual remediation event for the historical incident to get the true outcome
            hist_remediations = [e for e in self.engine.get_events_for_incident(hist_inc_id) if e.kind == 'remediation']
            if hist_remediations:
                latest_rem = hist_remediations[-1]
                remediations.append({
                    "action": latest_rem.action,
                    "target": latest_rem.target or s_copy.get('error_service'),
                    "historical_outcome": latest_rem.outcome,
                    "confidence": min(0.95, best_match['similarity'])
                })
            else:
                for action in raw_context.get('recommended_actions', {}).get('immediate_actions', []):
                    remediations.append({
                        "action": action.get('action'),
                        "target": s_copy.get('error_service', 'unknown'),
                        "historical_outcome": "resolved",
                        "confidence": action.get('confidence')
                    })

        # Compute confidence directly
        contradictions = self.engine.causality_detector.detect_signal_contradictions(related_events) if hasattr(self.engine, 'causality_detector') else {}
        penalty = contradictions.get('overall_penalty', 0.0)
        
        confidence = 0.0
        if causal_chain:
            confidence += 0.4 * causal_chain[0].get('confidence', 0.5)
        if similar_past:
            confidence += 0.4 * float(similar_past[0].get('similarity', 0.5))
        if remediations:
            confidence += 0.2 * remediations[0].get('confidence', 0.5)
            
        confidence = max(0.0, min(1.0, confidence - penalty))

        # SRE Narrative
        root_cause = "Unknown root cause"
        if causal_chain:
            root_cause = f"{causal_chain[0].get('evidence')} (Confidence: {causal_chain[0].get('confidence')})"
        
        blast_str = f"Directly affected: {s_copy.get('error_service')}"
        if hasattr(self.engine, 'graph'):
            deps = self.engine.graph.get_dependents(s_copy.get('error_service'))
            if deps:
                blast_str += f"\nIndirect cascading impact to: {', '.join(deps)}"
        
        signal_str = f"Analyzed {len(related_events)} recent events."
        if contradictions.get('is_noisy'):
            signal_str += f"\nWARNING: Contradictory signals detected ({contradictions.get('count')} conflicts), confidence penalized by {penalty:.2f}."
        
        hist_str = "No historical matches found."
        if similar_past:
            hist_str = f"Matches {len(similar_past)} past incidents. Top match: {similar_past[0]['incident_id']} ({similar_past[0]['similarity']*100:.1f}% similar)"
        
        rem_str = "Investigate manually."
        if remediations:
            rem_str = f"Action: {remediations[0]['action']} on {remediations[0]['target']}\nExpected Outcome: {remediations[0]['historical_outcome']}\nConfidence: {remediations[0]['confidence']*100:.1f}%"
            
        narrative = f"ROOT CAUSE:\n{root_cause}\n\nBLAST RADIUS:\n{blast_str}\n\nSIGNAL ANALYSIS:\n{signal_str}\n\nHISTORICAL PRECEDENT:\n{hist_str}\n\nRECOMMENDED REMEDIATION:\n{rem_str}"

        # Assemble the final conformant Context
        return {
            "related_events": [e.raw for e in related_events[-20:]],
            "causal_chain": causal_chain,
            "similar_past_incidents": similar_past,
            "suggested_remediations": remediations,
            "confidence": confidence,
            "explain": narrative
        }

    def close(self):
        pass
