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
        if not service_name:
            return 'internal_service'
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
        
        # Classify root and error services
        root_category = self.classify_service(canon_root)
        error_category = self.classify_service(canon_err)
        
        # Build complete fingerprint with all required fields
        fp = {
            'incident_id': inc_id,
            'canon_root': canon_root,
            'canon_err': canon_err,
            'root_cause_category': root_category,  # NEW: Required by similarity_score
            'error_category': error_category,      # NEW: For context
            'latent_family': family,
            'failure_pattern': {
                'type': error_metric,
                'severity': incident.get('severity', 'high')
            },
            'error_signature': {                   # NEW: Required by similarity_score
                'primary_error': error_metric
            },
            'blast_radius': {
                'depth': depth,
                'affected_service_categories': {root_category, error_category},  # NEW
                'user_visible': error_category == 'api_layer'  # NEW
            }
        }
        
        return fp

    def store_fingerprint(self, fp: Dict[str, Any]) -> None:
        self.fingerprint_db.append(fp)

    def similarity_score(self, fp1: Dict[str, Any], fp2: Dict[str, Any]) -> float:
        """
        Compute similarity between two incident fingerprints.
        Uses safe dictionary access to handle missing fields gracefully.
        """
        score = 0.0
        
        # Root cause category match (0.25 weight)
        if fp1.get('root_cause_category') == fp2.get('root_cause_category'):
            score += 0.25
        
        # Failure pattern match (0.20 weight)
        if fp1.get('failure_pattern', {}).get('type') == fp2.get('failure_pattern', {}).get('type'):
            score += 0.20
        
        # Blast radius similarity (0.20 weight)
        cats1 = set(fp1.get('blast_radius', {}).get('affected_service_categories', []))
        cats2 = set(fp2.get('blast_radius', {}).get('affected_service_categories', []))
        if cats1 or cats2:
            union_size = len(cats1 | cats2)
            if union_size > 0:
                overlap = len(cats1 & cats2) / union_size
                score += overlap * 0.20
        
        # Error signature match (0.10 weight)
        if fp1.get('error_signature', {}).get('primary_error') == fp2.get('error_signature', {}).get('primary_error'):
            score += 0.10
        
        # User visibility match (0.05 weight)
        if fp1.get('blast_radius', {}).get('user_visible') == fp2.get('blast_radius', {}).get('user_visible'):
            score += 0.05
        
        # Depth similarity (0.05 weight)
        depth1 = fp1.get('blast_radius', {}).get('depth', 0)
        depth2 = fp2.get('blast_radius', {}).get('depth', 0)
        depth_diff = abs(depth1 - depth2)
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

    def extract_morphing_invariant_fingerprint(self, causality: dict, incident_dict: dict) -> dict:
        root_cause = causality.get('root_cause_service', 'unknown')
        canonical_root = self.engine.store.get_current_service_name(root_cause)
        
        failure_modes = set()
        for event in causality.get('related_events', []):
            if event.kind == 'metric' and event.name in ['latency_p99_ms', 'latency_p95_ms']:
                failure_modes.add('latency_spike')
            elif event.kind == 'metric' and event.name in ['error_rate', 'error_count']:
                failure_modes.add('error_spike')
            elif event.kind == 'log' and event.level in ['error', 'critical']:
                failure_modes.add('application_error')
            elif event.kind == 'metric' and event.name in ['cpu_usage', 'memory_usage']:
                failure_modes.add('resource_exhaustion')
        
        if not failure_modes:
            if 'latency' in incident_dict.get('trigger', '').lower():
                failure_modes.add('latency_spike')
            elif 'error' in incident_dict.get('trigger', '').lower():
                failure_modes.add('error_spike')
        
        deploy_events = [e for e in causality.get('related_events', []) if e.kind == 'deploy']
        behavioral_family = 'deploy_incident' if deploy_events else 'operational_incident'
        
        impacted_count = len(causality.get('impacted_services', set()))
        if impacted_count == 1:
            blast_radius_family = 'isolated'
        elif impacted_count <= 3:
            blast_radius_family = 'multi_service_localized'
        else:
            blast_radius_family = 'cascading_multi_service'
        
        fingerprint = {
            'canonical_root_cause': canonical_root,
            'failure_modes': sorted(list(failure_modes)),
            'behavioral_family': behavioral_family,
            'blast_radius_family': blast_radius_family,
            'impacted_services': sorted(list(causality.get('impacted_services', set()))),
            'remediation_type': self._infer_remediation_type(causality),
            'morphism_invariants': {
                'is_deploy_induced': len(deploy_events) > 0,
                'has_transitive_effects': len(causality.get('transitive_causes', {}).get('transitive', set())) > 0,
            }
        }
        
        return fingerprint

    def _infer_remediation_type(self, causality: dict) -> str:
        deploy_events = [e for e in causality.get('related_events', []) if e.kind == 'deploy']
        if deploy_events:
            return 'rollback'
        
        resource_metrics = [e for e in causality.get('related_events', []) 
                           if e.kind == 'metric' and e.name in ['cpu_usage', 'memory_usage']]
        if resource_metrics:
            return 'scale'
        
        return 'generic_restart'
