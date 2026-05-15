from typing import Dict, Any, List

class IncidentIndex:
    """
    Topic 5: Pattern Matching.
    Semantic search engine storing fingerprints and enabling multi-dimensional
    historical incident retrieval with explainable rankings.
    """
    def __init__(self, engine):
        self.engine = engine
        self.incidents = []
        
    def add_incident(self, incident_id: str, fingerprint: Dict[str, Any], metadata: Dict[str, Any]) -> None:
        record = {
            'incident_id': incident_id,
            'fingerprint': fingerprint,
            'metadata': metadata
        }
        self.incidents.append(record)
        
    def _get_error_family(self, error: str) -> str:
        error_low = error.lower()
        if 'timeout' in error_low or 'deadline' in error_low:
            return 'timeout'
        if '500' in error_low or '503' in error_low or '5xx' in error_low:
            return 'server_error'
        if 'connection' in error_low or 'refused' in error_low:
            return 'network_error'
        return 'other'

    def _get_related_categories(self, cat: str) -> List[str]:
        if cat == 'payment_processor':
            return ['api_layer', 'database']
        if cat == 'database':
            return ['payment_processor', 'cache']
        if cat == 'cache':
            return ['database', 'api_layer']
        if cat == 'message_queue':
            return ['internal_service']
        if cat == 'api_layer':
            return ['payment_processor', 'internal_service', 'frontend']
        return []

    def _get_related_patterns(self, pattern: str) -> List[str]:
        if pattern == 'latency_spike':
            return ['timeout_cascade']
        if pattern == 'timeout_cascade':
            return ['latency_spike', 'error_spike']
        if pattern == 'error_spike':
            return ['resource_exhaustion', 'timeout_cascade']
        return []
        
    def similarity_score(self, current: Dict[str, Any], historical: Dict[str, Any]) -> Dict[str, Any]:
        score = 0.0
        matching_dimensions = []
        differing_dimensions = []
        
        # Root cause
        c_root = current.get('root_cause_category')
        h_root = historical.get('root_cause_category')
        if c_root == h_root:
            score += 0.30
            matching_dimensions.append(f'root_cause: {c_root} (exact)')
        elif h_root in self._get_related_categories(c_root):
            score += 0.10
            matching_dimensions.append(f'root_cause: related ({c_root} vs {h_root})')
        else:
            differing_dimensions.append(f'root_cause: {c_root} vs {h_root}')
            
        # Failure pattern
        c_pat = current.get('failure_pattern', {})
        h_pat = historical.get('failure_pattern', {})
        c_type = c_pat.get('type')
        h_type = h_pat.get('type')
        if c_type == h_type:
            score += 0.25
            matching_dimensions.append(f'failure_pattern: {c_type} (exact)')
        elif h_type in self._get_related_patterns(c_type):
            score += 0.15
            matching_dimensions.append(f'failure_pattern: related ({c_type} vs {h_type})')
        else:
            differing_dimensions.append(f'failure_pattern: {c_type} vs {h_type}')
            
        # Severity
        sev_map = {'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
        c_sev = sev_map.get(c_pat.get('severity', 'low'), 1)
        h_sev = sev_map.get(h_pat.get('severity', 'low'), 1)
        if abs(c_sev - h_sev) <= 1:
            score += 0.05
            matching_dimensions.append(f'severity: similar ({c_pat.get("severity", "low")} vs {h_pat.get("severity", "low")})')
        else:
            differing_dimensions.append(f'severity: different ({c_pat.get("severity", "low")} vs {h_pat.get("severity", "low")})')
            
        # Blast radius
        c_blast = current.get('blast_radius', {})
        h_blast = historical.get('blast_radius', {})
        c_cats = set(c_blast.get('affected_service_categories', []))
        h_cats = set(h_blast.get('affected_service_categories', []))
        if c_cats or h_cats:
            jaccard = len(c_cats & h_cats) / len(c_cats | h_cats)
            score += jaccard * 0.20
            matching_dimensions.append(f'blast_radius: {jaccard*100:.0f}% overlap')
            
        c_depth = c_blast.get('depth', 0)
        h_depth = h_blast.get('depth', 0)
        if abs(c_depth - h_depth) <= 1:
            score += 0.05
            matching_dimensions.append(f'depth: similar ({c_depth} vs {h_depth})')
            
        # Error signature
        c_err = current.get('error_signature', {}).get('primary_error', '')
        h_err = historical.get('error_signature', {}).get('primary_error', '')
        if c_err == h_err:
            score += 0.15
            matching_dimensions.append(f'primary_error: {c_err} (exact)')
        elif self._get_error_family(c_err) == self._get_error_family(h_err):
            score += 0.08
            matching_dimensions.append(f'primary_error: family match ({c_err} vs {h_err})')
        else:
            differing_dimensions.append(f'primary_error: {c_err} vs {h_err}')
            
        # User impact
        if c_blast.get('user_visible') == h_blast.get('user_visible'):
            score += 0.05
            vis = 'Yes' if c_blast.get('user_visible') else 'No'
            matching_dimensions.append(f'user_visible: {vis} (match)')
            
        return {
            'score': min(score, 1.0),
            'matching_dimensions': matching_dimensions,
            'differing_dimensions': differing_dimensions
        }
        
    def search(self, query_fingerprint: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
        results = []
        for hist in self.incidents:
            hist_fp = hist['fingerprint']
            sim = self.similarity_score(query_fingerprint, hist_fp)
            
            if sim['score'] >= 0.5:
                # Build explanation
                expl_lines = [f"Incident #{hist['incident_id']} is {sim['score']*100:.0f}% similar because:"]
                for md in sim['matching_dimensions']:
                    expl_lines.append(f"  ✓ {md}")
                for dd in sim['differing_dimensions']:
                    expl_lines.append(f"  ✗ {dd}")
                    
                fix = hist['metadata'].get('fix_applied', 'Unknown fix')
                mttr = hist['metadata'].get('mttr', 0)
                expl_lines.append(f"\nThis incident was fixed by: {fix}, taking {mttr}s.")
                
                rec_action = 'Apply same fix with high confidence' if sim['score'] >= 0.8 else 'Review fix for relevance'
                
                results.append({
                    'rank': 0,
                    'incident_id': hist['incident_id'],
                    'similarity_score': sim['score'],
                    'matching_dimensions': sim['matching_dimensions'],
                    'differing_dimensions': sim['differing_dimensions'],
                    'historical_context': hist['metadata'],
                    'recommendation': {
                        'action': rec_action,
                        'expected_mttr': mttr,
                        'confidence': sim['score']
                    },
                    'explanation': "\n".join(expl_lines)
                })
                
        results.sort(key=lambda x: x['similarity_score'], reverse=True)
        for i, res in enumerate(results):
            res['rank'] = i + 1
            
        return results[:limit]
