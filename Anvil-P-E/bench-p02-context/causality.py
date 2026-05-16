from datetime import timedelta
from typing import Dict, Any, List

class CausalityDetector:
    """
    Temporal Causality Detection (Topic 3).
    Correlates deploys to latency/error spikes via dependency paths.
    """
    def __init__(self, engine):
        self.engine = engine
        
    def analyze_incident(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        """
        Identify causal chains for an incident by evaluating candidate deploy events.
        """
        detected_at = incident['detected_at']
        error_service = incident['error_service']
        
        # Suspect window: last 120 minutes
        window_start = detected_at - timedelta(minutes=120)
        
        events_in_window = self.engine.get_events_in_time_window(window_start, detected_at)
        deploy_events = [e for e in events_in_window if e.kind == 'deploy']
        
        candidates = []
        for deploy in deploy_events:
            deployed_svc = deploy.service
            if not deployed_svc:
                continue
                
            has_direct = False
            has_trans = False
            
            canon_err = self.engine.graph.get_canonical_name(error_service)
            canon_dep = self.engine.graph.get_canonical_name(deployed_svc)
            
            if canon_dep in self.engine.graph.get_dependencies(canon_err):
                has_direct = True
            elif self.engine.graph.has_path(canon_err, canon_dep):
                has_trans = True
                
            if not has_direct and not has_trans and canon_err != canon_dep:
                continue # No path
                
            # Symptom Detection
            deploy_ts = deploy.ts
            symptom_window_end = min(deploy_ts + timedelta(minutes=15), detected_at)
            post_deploy_metrics = self.engine.get_events_in_time_window(deploy_ts, symptom_window_end)
            
            deployed_service_spiked = False
            for m in post_deploy_metrics:
                if m.kind == 'metric' and self.engine.graph.get_canonical_name(m.service) == canon_dep:
                    if m.value and m.value > getattr(m, 'baseline', 0) * 2: # simplistic spike check
                        deployed_service_spiked = True
                        break
            
            # Score Calculation
            confidence = 0.0
            if has_direct:
                confidence += 0.30
            elif has_trans:
                confidence += 0.10
                
            if deployed_service_spiked:
                confidence += 0.25
                
            time_diff = (detected_at - deploy_ts).total_seconds() / 60.0
            if time_diff <= 5:
                confidence += 0.20
            elif time_diff <= 15:
                confidence += 0.10
            if time_diff > 60:
                confidence -= 0.15
                
            if len(deploy_events) == 1:
                confidence += 0.10
            else:
                confidence -= 0.10 * (len(deploy_events) - 1)
                
            confidence = max(0.0, min(1.0, confidence))
            
            candidates.append({
                'root_cause_service': deployed_svc,
                'root_cause_deploy': {
                    'version': deploy.version,
                    'timestamp': deploy.ts
                },
                'confidence': round(confidence, 2),
                'causal_chain': [
                    {
                        'step': 1,
                        'service': deployed_svc,
                        'event_type': 'deploy',
                        'event_time': deploy.ts,
                        'cause_event_id': deploy.id,
                        'effect_event_id': incident.get('id', 'unknown')
                    }
                ]
            })
            
        candidates.sort(key=lambda x: x['confidence'], reverse=True)
        
        if not candidates:
            return {'incident_id': incident.get('id'), 'confidence': 0.0, 'candidates': []}
            
        best = candidates[0]
        root_cause_svc = best['root_cause_service']
        
        # Find downstream services that were affected
        downstream_services = self._find_downstream_effects(root_cause_svc, events_in_window)
        
        # Build complete causal chain
        causal_chain = [{
            'step': 1,
            'service': root_cause_svc,
            'event_type': 'deploy',
            'event_time': best['root_cause_deploy']['timestamp']
        }]
        
        # Add downstream effects to causal chain
        for idx, downstream_svc in enumerate(downstream_services, start=2):
            causal_chain.append({
                'step': idx,
                'service': downstream_svc,
                'event_type': 'downstream_error',
                'confidence': 0.65  # Lower confidence for inferred effects
            })
            
        result = {
            'incident_id': incident.get('id', 'unknown'),
            'root_cause_service': root_cause_svc,
            'root_cause_deploy': best['root_cause_deploy'],
            'confidence': best['confidence'],
            'causal_chain': causal_chain,  # Now includes downstream effects!
            'all_candidates': candidates,
            'downstream_services': downstream_services
        }
        
        root_cause = result.get('root_cause_service')
        if root_cause:
            transitive = self.get_transitive_causes(root_cause, max_hops=2)
            result['transitive_causes'] = transitive
            
            for svc in transitive['direct']:
                result['causal_chain'].append({
                    'source': svc,
                    'target': root_cause,
                    'confidence': 0.75,
                    'evidence': 'transitive_dependency'
                })
        return result

    def get_transitive_causes(self, target_service: str, max_hops: int = 2) -> dict:
        upstream_direct = set()
        upstream_transitive = set()
        hop_distance = {target_service: 0}
        
        queue = [(target_service, 0)]
        visited = {target_service}
        
        while queue:
            current_service, current_hop = queue.pop(0)
            
            if current_hop >= max_hops:
                continue
            
            dependents = self.engine.graph.get_dependents(current_service)
            
            for dependent in dependents:
                if dependent not in visited:
                    visited.add(dependent)
                    next_hop = current_hop + 1
                    hop_distance[dependent] = next_hop
                    
                    if next_hop == 1:
                        upstream_direct.add(dependent)
                    elif next_hop == 2:
                        upstream_transitive.add(dependent)
                    
                    queue.append((dependent, next_hop))
        
        return {
            'direct': upstream_direct,
            'transitive': upstream_transitive,
            'all_upstream': upstream_direct | upstream_transitive,
            'hop_distance': hop_distance
        }

    def _find_downstream_effects(self, root_service: str, events_in_window: List[Any]) -> List[str]:
        """
        Given a failing root service, find all downstream services that errored
        because of it (within the dependency graph).
        
        Args:
            root_service: The root cause service
            events_in_window: All events in the incident window
        
        Returns:
            List of service names that depend on root_service and showed errors
        """
        downstream = []
        canon_root = self.engine.graph.get_canonical_name(root_service)
        
        # Get all services in the system
        all_services = self.engine.graph.get_all_services()
        
        for svc in all_services:
            if svc == canon_root:
                continue
            
            # Check if this service depends on the root cause (has path TO root)
            if self.engine.graph.has_path(svc, canon_root):
                # Check if this service showed errors in our time window
                svc_events = [e for e in events_in_window 
                             if e.service and self.engine.graph.get_canonical_name(e.service) == svc]
                
                svc_errors = [e for e in svc_events 
                             if (e.kind == 'log' and e.level in ['error', 'critical'])
                             or (e.kind == 'metric' and e.value and e.value > 3000)]
                
                if svc_errors:  # Only include if we have error evidence
                    downstream.append(svc)
        
        return downstream

    def detect_signal_contradictions(self, events: list) -> dict:
        contradictions = []
        services_in_incident = set()
        
        events_by_service = {}
        for event in events:
            if event.service:
                if event.service not in events_by_service:
                    events_by_service[event.service] = {'metrics': [], 'logs': [], 'traces': []}
                
                if event.kind == 'metric':
                    events_by_service[event.service]['metrics'].append(event)
                elif event.kind == 'log':
                    events_by_service[event.service]['logs'].append(event)
                elif event.kind == 'trace':
                    events_by_service[event.service]['traces'].append(event)
                
                services_in_incident.add(event.service)
        
        for service, event_groups in events_by_service.items():
            high_latency_metrics = [
                e.value for e in event_groups['metrics']
                if e.name in ['latency_p99_ms', 'latency_p95_ms'] and e.value and e.value > 3000
            ]
            error_logs = [
                e for e in event_groups['logs']
                if e.level in ['error', 'critical']
            ]
            
            if high_latency_metrics and not error_logs:
                contradictions.append({
                    'service': service,
                    'conflict_type': 'metric_without_error_logs',
                    'confidence_penalty': 0.15,
                    'explanation': f"High latency ({max(high_latency_metrics):.0f}ms) but no error logs (may indicate external dependency)"
                })
            
            low_latency_metrics = [
                e.value for e in event_groups['metrics']
                if e.name in ['latency_p99_ms', 'latency_p95_ms'] and e.value and e.value < 500
            ]
            
            if error_logs and low_latency_metrics:
                contradictions.append({
                    'service': service,
                    'conflict_type': 'error_logs_with_low_latency',
                    'confidence_penalty': 0.10,
                    'explanation': "Error logs present but latency is low (may be transient/handled error)"
                })
        
        overall_penalty = min(sum(c['confidence_penalty'] for c in contradictions), 0.4)
        is_noisy = overall_penalty > 0.25
        
        return {
            'contradictions': contradictions,
            'overall_penalty': overall_penalty,
            'is_noisy': is_noisy,
            'count': len(contradictions)
        }
