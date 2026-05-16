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
                        'event_time': deploy.ts
                    }
                ]
            })
            
        candidates.sort(key=lambda x: x['confidence'], reverse=True)
        
        if not candidates:
            return {'incident_id': incident.get('id'), 'confidence': 0.0, 'candidates': []}
            
        best = candidates[0]
        return {
            'incident_id': incident.get('id', 'unknown'),
            'root_cause_service': best['root_cause_service'],
            'root_cause_deploy': best['root_cause_deploy'],
            'confidence': best['confidence'],
            'causal_chain': best['causal_chain'],
            'all_candidates': candidates
        }
