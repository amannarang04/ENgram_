from adapters.myteam import EngineAdapter

def test_5_level_topology_drift():
    """
    Test that engine handles multiple sequential renames.
    
    Timeline:
      payments-svc -> billing-svc -> payment-processor -> authz-svc -> paymentauth-v2
    """
    
    events = [
        # Original incident
        {'ts': '2026-01-01T10:00:00Z', 'kind': 'deploy', 'service': 'payments-svc', 'version': 'v1.0', 'actor': 'ci'},
        {'ts': '2026-01-01T10:04:00Z', 'kind': 'trace', 'trace_id': 'tr0', 'spans': [{'svc': 'checkout-api'}, {'svc': 'payments-svc'}]},
        {'ts': '2026-01-01T10:05:00Z', 'kind': 'log', 'service': 'checkout-api', 'level': 'error', 'msg': 'timeout calling payments-svc', 'trace_id': 'tr1'},
        {'ts': '2026-01-01T10:10:00Z', 'kind': 'incident_signal', 'incident_id': 'INC-001', 'service': 'checkout-api', 'trigger': 'alert:error-rate>5%'},
        {'ts': '2026-01-01T11:00:00Z', 'kind': 'remediation', 'incident_id': 'INC-001', 'action': 'rollback', 'target': 'payments-svc', 'outcome': 'resolved'},
        
        # Renames
        {'ts': '2026-02-01T00:00:00Z', 'kind': 'topology', 'change': 'rename', 'from_': 'payments-svc', 'to': 'billing-svc'},
        {'ts': '2026-03-01T00:00:00Z', 'kind': 'topology', 'change': 'rename', 'from_': 'billing-svc', 'to': 'payment-processor'},
        {'ts': '2026-04-01T00:00:00Z', 'kind': 'topology', 'change': 'rename', 'from_': 'payment-processor', 'to': 'authz-svc'},
        {'ts': '2026-05-01T00:00:00Z', 'kind': 'topology', 'change': 'rename', 'from_': 'authz-svc', 'to': 'paymentauth-v2'},
        
        # Recurring incident (same root cause)
        {'ts': '2026-05-10T10:00:00Z', 'kind': 'deploy', 'service': 'paymentauth-v2', 'version': 'v1.1', 'actor': 'ci'},
        {'ts': '2026-05-10T10:04:00Z', 'kind': 'trace', 'trace_id': 'tr2', 'spans': [{'svc': 'checkout-api'}, {'svc': 'paymentauth-v2'}]},
        {'ts': '2026-05-10T10:05:00Z', 'kind': 'log', 'service': 'checkout-api', 'level': 'error', 'msg': 'timeout calling paymentauth-v2', 'trace_id': 'tr2'},
        {'ts': '2026-05-10T10:10:00Z', 'kind': 'incident_signal', 'incident_id': 'INC-002', 'service': 'checkout-api', 'trigger': 'alert:error-rate>5%'},
    ]
    
    adapter = EngineAdapter()
    adapter.ingest(events)
    
    # Test reconstruction
    signal = {
        'incident_id': 'INC-002',
        'ts': '2026-05-10T10:10:00Z',
        'service': 'checkout-api',
        'trigger': 'alert:error-rate>5%'
    }
    
    context = adapter.reconstruct_context(signal)
    
    # Assertions
    assert len(context.get('similar_past_incidents', [])) > 0, "Should find INC-001 despite renames"
    assert context['similar_past_incidents'][0]['incident_id'] == 'INC-001'
    assert context['similar_past_incidents'][0]['similarity'] >= 0.7, "Similarity should be high despite topology drift"
    assert len(context.get('suggested_remediations', [])) > 0, "Should suggest rollback"
    assert context['suggested_remediations'][0]['action'] == 'rollback'
    assert len(context.get('related_events', [])) > 0, "Should include related events"
    assert len(context.get('causal_chain', [])) > 0, "Should identify causal chain"
    
    print("✅ Test passed: 5-level topology drift handling")

def test_decoy_incident():
    """
    Test that engine doesn't match incidents with no historical precedent.
    """
    
    events = [
        # No historical precedent for new-payment-service
        {'ts': '2026-05-10T16:00:00Z', 'kind': 'deploy', 'service': 'new-payment-service', 'version': 'v0.1.0', 'actor': 'ci'},
        {'ts': '2026-05-10T16:05:00Z', 'kind': 'metric', 'service': 'new-payment-service', 'name': 'cpu_usage', 'value': 95},
        {'ts': '2026-05-10T16:10:00Z', 'kind': 'incident_signal', 'incident_id': 'INC-DECOY', 'service': 'new-payment-service', 'trigger': 'alert:cpu>80%'},
    ]
    
    adapter = EngineAdapter()
    adapter.ingest(events)
    
    signal = {
        'incident_id': 'INC-DECOY',
        'ts': '2026-05-10T16:10:00Z',
        'service': 'new-payment-service',
        'trigger': 'alert:cpu>80%'
    }
    
    context = adapter.reconstruct_context(signal)
    
    # Assertions
    assert len(context.get('similar_past_incidents', [])) == 0, "Should not find any match for decoy"
    assert len([r for r in context.get('suggested_remediations', []) if r.get('confidence', 0) >= 0.5]) == 0, "Should not suggest high-confidence remediation"
    assert context.get('confidence', 0) < 0.5, "Overall confidence should be low for decoy"
    
    print("✅ Test passed: Decoy incident handling")

if __name__ == "__main__":
    print("Running Edge Case Tests...")
    test_5_level_topology_drift()
    test_decoy_incident()
    print("All edge case tests passed successfully!")
