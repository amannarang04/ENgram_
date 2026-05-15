import networkx as nx
from typing import List, Dict, Set, Any, Optional

class ServiceDependencyGraph:
    """
    World-class service dependency graph tracking dependencies,
    weights, and deployed versions while transparently handling renames.
    """
    
    def __init__(self):
        self.graph = nx.DiGraph()
        self.service_versions: Dict[str, Set[str]] = {}
        self.last_deployed_version: Dict[str, str] = {}
        self.rename_map: Dict[str, str] = {}
        
    def get_canonical_name(self, service_name: str, rename_map: Optional[Dict[str, str]] = None) -> str:
        """Resolve service name to canonical name following rename chains."""
        if rename_map is not None:
            self.rename_map.update(rename_map)
            
        current = service_name
        seen = set()
        while current in self.rename_map and current not in seen:
            seen.add(current)
            current = self.rename_map[current]
        return current
        
    def build_from_events(self, events: List[Any], rename_map: Dict[str, str]) -> None:
        """
        Build dependency graph from trace events.
        """
        self.rename_map = rename_map
        
        for event in events:
            if event.kind == 'trace' and getattr(event, 'spans', None):
                spans = event.spans
                for i in range(len(spans) - 1):
                    svc_a = spans[i].get('svc')
                    svc_b = spans[i+1].get('svc')
                    
                    if not svc_a or not svc_b:
                        continue
                        
                    canon_a = self.get_canonical_name(svc_a)
                    canon_b = self.get_canonical_name(svc_b)
                    
                    if canon_a == canon_b:
                        continue
                        
                    if self.graph.has_edge(canon_a, canon_b):
                        self.graph[canon_a][canon_b]['weight'] += 1
                    else:
                        self.graph.add_edge(canon_a, canon_b, weight=1)
                        
    def track_deployment(self, deploy_events: List[Any]) -> None:
        """Track version deployments."""
        sorted_events = sorted([e for e in deploy_events if e.kind == 'deploy' and e.ts], key=lambda x: x.ts)
        
        for event in sorted_events:
            if event.service and event.version:
                canon_svc = self.get_canonical_name(event.service)
                if canon_svc not in self.service_versions:
                    self.service_versions[canon_svc] = set()
                self.service_versions[canon_svc].add(event.version)
                self.last_deployed_version[canon_svc] = event.version
                
                if not self.graph.has_node(canon_svc):
                    self.graph.add_node(canon_svc)

    def get_dependencies(self, service: str) -> List[str]:
        canon = self.get_canonical_name(service)
        if self.graph.has_node(canon):
            return list(self.graph.successors(canon))
        return []
        
    def get_dependents(self, service: str) -> List[str]:
        canon = self.get_canonical_name(service)
        if self.graph.has_node(canon):
            return list(self.graph.predecessors(canon))
        return []
        
    def has_path(self, from_service: str, to_service: str) -> bool:
        canon_from = self.get_canonical_name(from_service)
        canon_to = self.get_canonical_name(to_service)
        if self.graph.has_node(canon_from) and self.graph.has_node(canon_to):
            return nx.has_path(self.graph, canon_from, canon_to)
        return False
        
    def get_edge_weight(self, from_service: str, to_service: str) -> int:
        canon_from = self.get_canonical_name(from_service)
        canon_to = self.get_canonical_name(to_service)
        if self.graph.has_edge(canon_from, canon_to):
            return self.graph[canon_from][canon_to]['weight']
        return 0
        
    def get_transitive_dependencies(self, service: str, max_depth: int = 3) -> List[str]:
        canon = self.get_canonical_name(service)
        if not self.graph.has_node(canon):
            return []
            
        reachable = set()
        queue = [(canon, 0)]
        while queue:
            curr, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for succ in self.graph.successors(curr):
                if succ not in reachable:
                    reachable.add(succ)
                    queue.append((succ, depth + 1))
        return list(reachable)

    def get_all_services(self) -> Set[str]:
        return set(self.graph.nodes())
        
    def get_graph_stats(self) -> Dict[str, Any]:
        num_edges = self.graph.number_of_edges()
        avg_weight = 0
        if num_edges > 0:
            avg_weight = sum(d['weight'] for _, _, d in self.graph.edges(data=True)) / num_edges
            
        return {
            'num_services': self.graph.number_of_nodes(),
            'num_dependencies': num_edges,
            'avg_edge_weight': round(avg_weight, 2)
        }
