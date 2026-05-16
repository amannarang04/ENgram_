from adapters.myteam import EngineAdapter
from schema import Context

def validate_context_schema(context: Context) -> tuple[bool, str]:
    """Validate that context matches official schema."""
    
    # Check required fields
    required_fields = [
        'related_events',
        'causal_chain',
        'similar_past_incidents',
        'suggested_remediations',
        'confidence',
        'explain'
    ]
    
    for field in required_fields:
        if field not in context:
            return False, f"Missing required field: {field}"
    
    # Type checks
    if not isinstance(context['related_events'], list):
        return False, "related_events must be list"
    
    if not isinstance(context['causal_chain'], list):
        return False, "causal_chain must be list"
    
    for edge in context['causal_chain']:
        if 'cause_event_id' not in edge or edge['cause_event_id'] == 'unknown':
            print("⚠️  WARNING: causal_chain has unknown cause_event_id")
        if 'effect_event_id' not in edge or edge['effect_event_id'] == 'unknown':
            print("⚠️  WARNING: causal_chain has unknown effect_event_id")
    
    if not isinstance(context['similar_past_incidents'], list):
        return False, "similar_past_incidents must be list"
    
    if not isinstance(context['suggested_remediations'], list):
        return False, "suggested_remediations must be list"
    
    if not isinstance(context['confidence'], (int, float)) or not (0 <= context['confidence'] <= 1):
        return False, "confidence must be float between 0 and 1"
    
    if not isinstance(context['explain'], str):
        return False, "explain must be string"
    
    if not context['explain'] or len(context['explain']) < 20:
        return False, "explain narrative too short"
    
    return True, "✅ Schema validation passed"

if __name__ == "__main__":
    print("Running submission validation...")
    
    adapter = EngineAdapter()
    
    # Test with simple scenario
    events = [
        {'ts': '2026-05-10T10:00:00Z', 'kind': 'deploy', 'service': 'api', 'version': 'v1.0', 'actor': 'ci'},
        {'ts': '2026-05-10T10:05:00Z', 'kind': 'log', 'service': 'web', 'level': 'error', 'msg': 'timeout', 'trace_id': 'tr1'},
        {'ts': '2026-05-10T10:10:00Z', 'kind': 'incident_signal', 'incident_id': 'INC-1', 'service': 'web', 'trigger': 'alert:error>5%'},
    ]
    
    adapter.ingest(events)
    
    signal = {
        'incident_id': 'INC-1',
        'ts': '2026-05-10T10:10:00Z',
        'service': 'web',
        'trigger': 'alert:error>5%'
    }
    
    context = adapter.reconstruct_context(signal)
    
    valid, msg = validate_context_schema(context)
    print(msg)
    
    if valid:
        print("\n✅ Submission is valid and ready for benchmark!")
    else:
        print(f"\n❌ Submission has issues:\n{msg}")
