from typing import Dict, Any, List

class IncidentFingerprinter:
    """
    Incident Fingerprinting (Topic 4).
    Creates structural signatures for incidents immune to drift.
    """
    def __init__(self, engine):
        self.engine = engine
        self.fingerprint_db = []
        
    def classify_service(self, service_name: str) -> str:
        """Classify a service into functional categories."""
        name = service_name.lower()
        if any(x in name for x in ['payment', 'billing', 'stripe', 'checkout']):
            return 'payment_processor'
        elif any(x in name for x in ['postgres', 'mysql', 'db', 'database', 'data']):
            return 'database'
        elif any(x in name for x in ['redis', 'memcached', 'cache']):
            return 'cache'
        elif any(x in name for x in ['kafka', 'rabbitmq', 'queue', 'mq']):
            return 'message_queue'
        elif any(x in name for x in ['api-gateway', 'frontend', 'web-ui', 'client', 'api']):
            return 'api_layer'
        return 'internal_service'

    def extract_fingerprint(self, causal_result: Dict[str, Any], incident: Dict[str, Any]) -> Dict[str, Any]:
        """Extract a semantic signature from a causal analysis result."""
        root_cause = causal_result.get('root_cause_service', 'unknown')
        error_svc = incident.get('error_service', '')
        
        canon_root = self.engine.graph.get_canonical_name(root_cause)
        canon_err = self.engine.graph.get_canonical_name(error_svc)
        
        depth = 0
        if self.engine.graph.has_path(canon_err, canon_root):
            depth = 1 if canon_root in self.engine.graph.get_dependencies(canon_err) else 3
            
        # Parse trigger: "alert:svc-01-r3/latency_p99_ms>3000" -> "latency_p99_ms>3000"
        trigger = incident.get('trigger', '')
        error_metric = trigger.split('/')[-1] if '/' in trigger else 'unknown'
        
        inc_id = incident.get('incident_id') or incident.get('id', '')
        family = inc_id.rsplit("-", 1)[-1] if "-" in inc_id else 'unknown'
            
        fp = {
            'incident_id': inc_id,
            'canon_root': canon_root,
            'canon_err': canon_err,
            'latent_family': family,
            'failure_pattern': {
                'type': error_metric,
                'severity': incident.get('severity', 'high')
            },
            'blast_radius': {
                'depth': depth
            }
        }
        return fp

    def store_fingerprint(self, fp: Dict[str, Any]) -> None:
        self.fingerprint_db.append(fp)

    def similarity_score(self, fp1: Dict[str, Any], fp2: Dict[str, Any]) -> float:
        score = 0.0
        
        # Root cause match
        if fp1['root_cause_category'] == fp2['root_cause_category']:
            score += 0.25
            
        # Failure pattern match
        if fp1['failure_pattern']['type'] == fp2['failure_pattern']['type']:
            score += 0.20
            
        # Blast radius similarity
        cats1 = set(fp1['blast_radius']['affected_service_categories'])
        cats2 = set(fp2['blast_radius']['affected_service_categories'])
        if cats1 or cats2:
            overlap = len(cats1 & cats2) / len(cats1 | cats2)
            score += overlap * 0.20
            
        # Error signature
        if fp1['error_signature']['primary_error'] == fp2['error_signature']['primary_error']:
            score += 0.10
            
        # User visibility
        if fp1['blast_radius']['user_visible'] == fp2['blast_radius']['user_visible']:
            score += 0.05
            
        # Depth similarity
        depth_diff = abs(fp1['blast_radius']['depth'] - fp2['blast_radius']['depth'])
        if depth_diff <= 1:
            score += 0.05
            
        return min(score, 1.0)
        
    def match_incident(self, new_fp: Dict[str, Any]) -> List[Dict[str, Any]]:
        matches = []
        for hist_fp in self.fingerprint_db:
            score = self.similarity_score(new_fp, hist_fp)
            matches.append({
                'historical_id': hist_fp['incident_id'],
                'similarity_score': round(score, 2)
            })
            
        matches.sort(key=lambda x: x['similarity_score'], reverse=True)
        return matches[:3]
