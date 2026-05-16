from engine import Engine
from datetime import datetime

# Recreate the worked example from the problem spec
events = [
    {"ts":"2026-05-10T14:21:30Z","kind":"deploy","service":"payments-svc","version":"v2.14.0","actor":"ci"},
    {"ts":"2026-05-10T14:22:01Z","kind":"log","service":"checkout-api","level":"error","msg":"timeout calling payments-svc","trace_id":"abc123"},
    {"ts":"2026-05-10T14:22:01Z","kind":"metric","service":"payments-svc","name":"latency_p99_ms","value":4820},
    {"ts":"2026-05-10T14:22:08Z","kind":"trace","trace_id":"abc123","spans":[{"svc":"checkout-api","dur_ms":5012},{"svc":"payments-svc","dur_ms":4980}]},
    {"ts":"2026-05-10T14:30:00Z","kind":"topology","change":"rename","from":"payments-svc","to":"billing-svc"},
    {"ts":"2026-05-10T14:32:11Z","kind":"incident_signal","incident_id":"INC-714","trigger":"alert:checkout-api/error-rate>5%"},
    {"ts":"2026-05-10T15:10:00Z","kind":"remediation","incident_id":"INC-714","action":"rollback","target":"billing-svc","version":"v2.13.4","outcome":"resolved"},
]

engine = Engine()
engine.ingest(events)

# The incident
signal = {"id": "INC-714", "service": "checkout-api", "detected_at": datetime.fromisoformat("2026-05-10T14:32:11+00:00")}

# Reconstruct context
try:
    ctx = engine.reconstruct_context(signal, mode='fast')
    print("PASS reconstruct_context executed successfully")
    print(f"  Related events: {len(ctx.get('related_events', []))}")
    print(f"  Causal chain: {len(ctx.get('causal_chain', []))}")
    print(f"  Past incidents: {len(ctx.get('similar_past_incidents', []))}")
    print(f"  Confidence: {ctx.get('confidence', 0):.2f}")
    print(f"\nWorked example test PASSED")
except Exception as e:
    print(f"FAIL Error: {e}")
    import traceback
    traceback.print_exc()
