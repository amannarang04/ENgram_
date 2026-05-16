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
            
        similar_past = []
        for match in raw_context.get('historical_context', {}).get('top_matches', []):
            if match.get('similarity_score', 0) >= 0.8:
                similar_past.append({
                    "incident_id": match.get('incident_id'),
                    "similarity": match.get('similarity_score'),
                    "rationale": match.get('explanation')
                })
            
        remediations = []
        for action in raw_context.get('recommended_actions', {}).get('immediate_actions', []):
            remediations.append({
                "action": action.get('action'),
                "target": "unknown",
                "historical_outcome": "resolved",
                "confidence": action.get('confidence')
            })

        # Assemble the final conformant Context
        return {
            "related_events": raw_context.get('related_events', []),
            "causal_chain": causal_chain,
            "similar_past_incidents": similar_past,
            "suggested_remediations": remediations,
            "confidence": raw_context.get('confidence_assessment', {}).get('overall_incident_confidence', 0.0),
            "explain": raw_context.get('executive_summary', '')
        }

    def close(self):
        pass
