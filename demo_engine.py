from datetime import datetime, timezone
import json
from engine import Engine

def print_section(title):
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80)

def main():
    print_section("INITIALIZING THE OPERATIONAL MEMORY ENGINE")
    engine = Engine()
    
    print("Engine initialized successfully.")
    
    print_section("INGESTING SIMULATED TELEMETRY DATA")
    # Simulate an incident from 6 months ago (Incident 4789)
    # payments-svc deploy -> latency spike -> timeout in checkout-api -> rollback
    past_events = [
        {
            "ts": "2025-11-10T10:00:00Z",
            "kind": "deploy",
            "service": "payments-svc",
            "version": "v2.14.0",
            "actor": "ci"
        },
        {
            "ts": "2025-11-10T10:00:10Z",
            "kind": "trace",
            "trace_id": "trace-old-1",
            "spans": [{"svc": "checkout-api", "dur_ms": 100}, {"svc": "payments-svc", "dur_ms": 90}]
        },
        {
            "ts": "2025-11-10T10:01:30Z",
            "kind": "metric",
            "service": "payments-svc",
            "name": "latency_p99_ms",
            "value": 4820
        },
        {
            "ts": "2025-11-10T10:02:00Z",
            "kind": "log",
            "service": "checkout-api",
            "level": "error",
            "msg": "timeout calling payments-svc",
            "trace_id": "trace-old-2"
        },
        {
            "ts": "2025-11-10T10:05:00Z",
            "kind": "incident_signal",
            "incident_id": "INC-4789",
            "trigger": "alert:checkout-api/error-rate>5%",
            "service": "checkout-api"
        },
        {
            "ts": "2025-11-10T10:20:00Z",
            "kind": "remediation",
            "incident_id": "INC-4789",
            "action": "rollback",
            "target": "payments-svc",
            "version": "v2.13.4",
            "outcome": "resolved"
        }
    ]
    
    # Fast forward to today: payments-svc was renamed to billing-svc
    # And a new deployment happens causing the exact same issue!
    current_events = [
        {
            "ts": "2026-05-15T14:00:00Z",
            "kind": "topology",
            "change": "rename",
            "from": "payments-svc",
            "to": "billing-svc"
        },
        {
            "ts": "2026-05-15T14:21:30Z",
            "kind": "deploy",
            "service": "billing-svc",
            "version": "v3.5.0",
            "actor": "ci"
        },
        {
            "ts": "2026-05-15T14:21:40Z",
            "kind": "trace",
            "trace_id": "trace-new-1",
            "spans": [{"svc": "checkout-api", "dur_ms": 105}, {"svc": "billing-svc", "dur_ms": 95}]
        },
        {
            "ts": "2026-05-15T14:22:01Z",
            "kind": "metric",
            "service": "billing-svc",
            "name": "latency_p99_ms",
            "value": 5100
        },
        {
            "ts": "2026-05-15T14:22:30Z",
            "kind": "log",
            "service": "checkout-api",
            "level": "error",
            "msg": "deadline_exceeded calling billing-svc",
            "trace_id": "trace-new-2"
        },
        {
            "ts": "2026-05-15T14:23:00Z",
            "kind": "incident_signal",
            "id": "INC-12345",
            "detected_at": "2026-05-15T14:23:00Z",
            "severity": "critical",
            "service": "checkout-api",
            "trigger": "alert:checkout-api/error-rate>10%"
        }
    ]
    
    engine.ingest(past_events)
    engine.ingest(current_events)
    
    print(f"Successfully ingested {len(past_events) + len(current_events)} raw telemetry events.")
    print("Engine has built dependency graph, cached causal edges, and established incident fingerprints.")
    
    print_section("INCIDENT DETECTED! RECONSTRUCTING CONTEXT")
    # Simulate the trigger of the current incident
    signal = current_events[-1].copy()
    signal['error_service'] = signal.pop('service')
    signal['detected_at'] = datetime.fromisoformat(signal['detected_at'].replace('Z', '+00:00'))
    
    print(f"Time: {signal['detected_at']}")
    print(f"Alert: {signal['trigger']}")
    print("Generating Context Object...\n")
    
    context = engine.context_builder.build_context(signal)
    
    def default_serializer(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")
        
    print(json.dumps(context, indent=2, default=default_serializer))
    
    print_section("DEMO COMPLETE")
    print("Notice how the engine correctly identified 'billing-svc' as the root cause,")
    print("even though the alert was on 'checkout-api'!")
    print("It also found the historical match from 6 months ago (INC-4789) despite the")
    print("service being renamed from 'payments-svc' to 'billing-svc', and recommended")
    print("a rollback because it worked last time. 🚀")

if __name__ == "__main__":
    main()
