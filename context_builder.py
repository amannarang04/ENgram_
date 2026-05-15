from typing import Dict, Any, List

class ContextBuilder:
    """
    Topic 6: Context Reconstruction.
    Assembles a unified Incident Context object from all previous topics
    to serve as a comprehensive decision artifact for ops teams.
    """
    def __init__(self, engine):
        self.engine = engine
        
    def _generate_executive_summary(self, root_cause: Dict[str, Any], blast: Dict[str, Any], best_match: Dict[str, Any]) -> str:
        rc_svc = root_cause.get('root_cause_service', 'Unknown_Service')
        rc_ver = root_cause.get('root_cause_deploy', {}).get('version', 'unknown_version')
        
        traffic = blast.get('estimated_customer_impact', {}).get('percentage_of_traffic', 0) * 100
        cascading = blast.get('cascading_impact', {}).get('all_affected_services', [])
        
        summary = f"{rc_svc} {rc_ver} deployment triggered an incident cascading to {len(cascading)} services. "
        summary += f"Affects roughly {traffic:.0f}% of traffic. "
        
        if best_match:
            fix = best_match.get('historical_context', {}).get('fix_applied', 'Unknown fix')
            hist_id = best_match.get('incident_id', 'Unknown')
            summary += f"Similar to incident #{hist_id}. Recommended action: {fix}."
        else:
            summary += "No highly similar past incidents found. Manual investigation required."
            
        return summary
        
    def _calculate_blast_radius(self, root_svc: str) -> Dict[str, Any]:
        """
        Calculates blast radius by traversing the graph backwards (dependents / callers)
        since failures propagate upstream to callers.
        """
        canon_root = self.engine.graph.get_canonical_name(root_svc)
        direct = self.engine.graph.get_dependents(canon_root)
        
        queue = [(canon_root, 0)]
        cascading = set()
        user_visible = False
        
        while queue:
            curr, depth = queue.pop(0)
            if depth > 0:
                cascading.add(curr)
                cat = self.engine.fingerprinter.classify_service(curr)
                if cat in ['api_layer', 'frontend']:
                    user_visible = True
                    
            for pred in self.engine.graph.get_dependents(curr):
                if pred not in cascading and pred != canon_root:
                    queue.append((pred, depth + 1))
                    
        cascading_list = list(cascading)
        
        return {
            'root_cause_service': root_svc,
            'directly_affected': {
                'services': direct,
                'count': len(direct)
            },
            'cascading_impact': {
                'all_affected_services': cascading_list,
                'total_services_down': len(cascading_list) + 1,
                'user_visible': user_visible
            },
            'estimated_customer_impact': {
                'percentage_of_traffic': 0.65 if user_visible else 0.05
            }
        }

    def build_context(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        """
        Builds the unified incident context object.
        """
        # 1. Metadata
        metadata = {
            'incident_id': incident.get('id', 'INC-UNKNOWN'),
            'detected_at': incident.get('detected_at'),
            'severity': incident.get('severity', 'high'),
            'status': 'ongoing'
        }
        
        # 3. Root Cause Analysis
        causality = self.engine.causality_detector.analyze_incident(incident)
        rc_svc = causality.get('root_cause_service', 'unknown')
        
        # 4. Blast Radius
        blast_radius = self._calculate_blast_radius(rc_svc)
        
        # 5. Historical Context (Fingerprinting + Pattern Matching)
        fp = self.engine.fingerprinter.extract_fingerprint(causality, incident)
        matches = self.engine.pattern_matcher.search(fp, limit=3)
        best_match = matches[0] if matches else None
        
        # 6. Recommended Actions
        actions = []
        if best_match and best_match['similarity_score'] >= 0.8:
            fix = best_match.get('historical_context', {}).get('fix_applied', 'Investigate')
            actions.append({
                'priority': 1,
                'action': fix,
                'confidence': best_match['similarity_score'],
                'rationale': f"Match with incident #{best_match.get('incident_id')} ({best_match['similarity_score']*100:.0f}% similarity)"
            })
        else:
            actions.append({
                'priority': 1,
                'action': 'Investigate root cause',
                'confidence': causality.get('confidence', 0.0),
                'rationale': 'No high-confidence historical matches found.'
            })
            
        # 8. Executive Summary
        exec_summary = self._generate_executive_summary(causality, blast_radius, best_match)
        
        # Assemble Final Context Object
        return {
            'incident_metadata': metadata,
            'root_cause_analysis': causality,
            'blast_radius': blast_radius,
            'historical_context': {'top_matches': matches},
            'recommended_actions': {'immediate_actions': actions},
            'confidence_assessment': {
                'root_cause_confidence': causality.get('confidence', 0.0),
                'fix_confidence': best_match['similarity_score'] if best_match else 0.0
            },
            'executive_summary': exec_summary
        }
