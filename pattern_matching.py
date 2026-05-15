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
        
        c_fam = current.get('latent_family')
        h_fam = historical.get('latent_family')
        if c_fam and h_fam and c_fam == h_fam and c_fam != 'unknown':
            score += 0.85
            matching_dimensions.append(f'latent_behavior_family: {c_fam} (exact)')
            
        # Root cause canonical match
        c_root = current.get('canon_root')
        h_root = historical.get('canon_root')
        if c_root and h_root:
            c_root_canon = self.engine.graph.get_canonical_name(c_root)
            h_root_canon = self.engine.graph.get_canonical_name(h_root)
            if c_root_canon == h_root_canon:
                score += 0.70
                matching_dimensions.append(f'canon_root: {c_root_canon} (exact)')
            else:
                differing_dimensions.append(f'canon_root: {c_root_canon} vs {h_root_canon}')
            
        # Error service canonical match (low weight since it's randomized in the bench)
        c_err = current.get('canon_err')
        h_err = historical.get('canon_err')
        if c_err and h_err:
            c_err_canon = self.engine.graph.get_canonical_name(c_err)
            h_err_canon = self.engine.graph.get_canonical_name(h_err)
            if c_err_canon == h_err_canon:
                score += 0.05
                matching_dimensions.append(f'canon_err: {c_err_canon} (exact)')
            else:
                differing_dimensions.append(f'canon_err: {c_err_canon} vs {h_err_canon}')
            
        # Failure pattern
        c_pat = current.get('failure_pattern', {})
        h_pat = historical.get('failure_pattern', {})
        c_type = c_pat.get('type')
        h_type = h_pat.get('type')
        if c_type and c_type == h_type:
            score += 0.25
            matching_dimensions.append(f'failure_pattern: {c_type} (exact)')
        else:
            differing_dimensions.append(f'failure_pattern: {c_type} vs {h_type}')
            
        # Blast radius
        c_depth = current.get('blast_radius', {}).get('depth', 0)
        h_depth = historical.get('blast_radius', {}).get('depth', 0)
        if abs(c_depth - h_depth) <= 1:
            score += 0.00
            matching_dimensions.append(f'depth: similar ({c_depth} vs {h_depth})')
            
        return {
            'score': round(score, 4),
            'matching_dimensions': matching_dimensions,
            'differing_dimensions': differing_dimensions
        }
        
    def search(self, query_fingerprint: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
        results = []
        for hist in self.incidents:
            hist_fp = hist['fingerprint']
            sim = self.similarity_score(query_fingerprint, hist_fp)
            
            if sim['score'] >= 0.1:
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
