from adapters.myteam import EngineAdapter

events = [
    {'ts': '2026-01-01T10:00:00Z', 'kind': 'deploy', 'service': 'payments-svc', 'version': 'v1.0', 'actor': 'ci'},
    {'ts': '2026-01-01T10:30:00Z', 'kind': 'metric', 'service': 'checkout-api', 'name': 'error_rate', 'value': 0.15},
    {'ts': '2026-01-01T10:35:00Z', 'kind': 'incident_signal', 'incident_id': 'INC-100', 'service': 'checkout-api', 'trigger': 'alert'},
    {'ts': '2026-01-01T11:00:00Z', 'kind': 'remediation', 'incident_id': 'INC-100', 'action': 'rollback', 'target': 'payments-svc', 'outcome': 'resolved'},
    {'ts': '2026-05-10T10:00:00Z', 'kind': 'deploy', 'service': 'payments-svc', 'version': 'v1.1', 'actor': 'ci'},
    {'ts': '2026-05-10T10:30:00Z', 'kind': 'metric', 'service': 'checkout-api', 'name': 'error_rate', 'value': 0.18},
    {'ts': '2026-05-10T10:35:00Z', 'kind': 'incident_signal', 'incident_id': 'INC-200', 'service': 'checkout-api', 'trigger': 'alert'},
]

adapter = EngineAdapter()
adapter.ingest(events)
signal = {'incident_id': 'INC-200', 'ts': '2026-05-10T10:35:00Z', 'service': 'checkout-api', 'trigger': 'alert'}
ctx = adapter.reconstruct_context(signal)

print(f"related_events: {len(ctx.get('related_events', []))}")
print(f"causal_chain: {len(ctx.get('causal_chain', []))}")
print(f"similar_past_incidents: {len(ctx.get('similar_past_incidents', []))}")
print(f"confidence: {ctx.get('confidence', 0)}")
