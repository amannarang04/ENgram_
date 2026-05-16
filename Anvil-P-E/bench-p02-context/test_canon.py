from graph_builder import ServiceDependencyGraph

graph = ServiceDependencyGraph()
rename_map = {'svc-01': 'svc-01-r7', 'svc-03': 'svc-03-r6'}
print(graph.get_canonical_name('svc-01-r7', rename_map))
