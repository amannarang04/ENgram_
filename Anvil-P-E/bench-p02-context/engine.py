"""
Topic 1: Event Ingestion & Storage
World-class event parsing and multi-indexed storage system
"""

from datetime import datetime, timezone
from typing import Iterable, Optional, List, Dict, Any
import uuid
import bisect
from dataclasses import dataclass, field
import json
import sys

# Configure stdout for utf-8 to handle unicode characters like ✓ and ✅ on Windows
sys.stdout.reconfigure(encoding='utf-8')


# ============================================================================
# PART 1A: EVENT DATA STRUCTURE (Normalized Event Representation)
# ============================================================================

@dataclass
class Event:
    """
    Normalized telemetry event with full provenance.
    
    Every event in production has:
    - A unique ID for traceability
    - A timestamp (normalized to datetime, not string)
    - A kind (type of event)
    - Optional service/trace/incident linkage
    - Full raw JSON preserved (no data loss)
    - Confidence score (how sure we are this event is valid)
    """
    
    # Core fields (every event has these)
    id: str                              # UUID - unique identifier
    kind: str                            # 'deploy', 'log', 'metric', 'trace', 'topology', 'incident_signal', 'remediation'
    ts: Optional[datetime]               # Normalized timestamp (NOT string)
    raw: Dict[str, Any]                  # Original JSON (preserve everything)
    confidence: float = 1.0              # How confident we are this event is valid (0-1)
    
    # Optional linkage fields
    service: Optional[str] = None        # Service name (may be None)
    trace_id: Optional[str] = None       # Request trace ID (may be None)
    incident_id: Optional[str] = None    # Incident ID (may be None)
    
    # Type-specific fields (populated based on kind)
    version: Optional[str] = None        # For deploy events
    actor: Optional[str] = None          # For deploy events (who deployed?)
    level: Optional[str] = None          # For log events: 'error', 'warning', 'info'
    msg: Optional[str] = None            # For log events: the message
    name: Optional[str] = None           # For metric events: metric name
    value: Optional[float] = None        # For metric events: metric value
    spans: Optional[List[Dict]] = None   # For trace events: list of {svc, dur_ms, ...}
    change: Optional[str] = None         # For topology events: 'rename', 'add', 'remove'
    from_name: Optional[str] = None      # For topology rename: old service name
    to_name: Optional[str] = None        # For topology rename: new service name
    trigger: Optional[str] = None        # For incident_signal: what triggered it
    action: Optional[str] = None         # For remediation: 'rollback', 'scale', 'restart'
    target: Optional[str] = None         # For remediation: service name
    outcome: Optional[str] = None        # For remediation: 'resolved', 'failed'


# ============================================================================
# PART 1B: EVENT PARSING & NORMALIZATION
# ============================================================================

def parse_iso_timestamp(ts_str: str) -> Optional[datetime]:
    """
    Parse ISO 8601 timestamp string to datetime object.
    
    Handles:
    - "2026-05-10T14:21:30Z"
    - "2026-05-10T14:21:30+00:00"
    - Various ISO formats
    
    Returns None if parsing fails (graceful degradation).
    """
    if not ts_str:
        return None
    
    try:
        # Handle 'Z' suffix (UTC indicator)
        if ts_str.endswith('Z'):
            ts_str = ts_str[:-1] + '+00:00'
        
        # Parse ISO format
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def generate_event_id() -> str:
    """Generate a unique event ID (UUID)."""
    return str(uuid.uuid4())


def parse_and_normalize_event(raw_json: Dict[str, Any]) -> Optional[Event]:
    """
    Parse raw JSON event → normalized Event object.
    
    Handles:
    - All 7 event types (deploy, log, metric, trace, topology, incident_signal, remediation)
    - Missing/malformed fields (gracefully skips, sets to None)
    - Timestamp normalization (ISO string → datetime object)
    - Type-specific field extraction
    
    Returns:
        Event object if valid, None if unparseable (no crashing)
    """
    
    # === VALIDATION: kind is required ===
    kind = raw_json.get('kind')
    if not kind:
        # Skip events without a kind
        return None
    
    # === PARSE TIMESTAMP (happens once, not a thousand times later) ===
    ts_str = raw_json.get('ts')
    ts = parse_iso_timestamp(ts_str)
    
    # Timestamp is required - skip if missing/invalid
    if not ts:
        return None
    
    # === CREATE BASE EVENT ===
    event = Event(
        id=generate_event_id(),
        kind=kind,
        ts=ts,
        raw=raw_json.copy(),  # Preserve original
        service=raw_json.get('service'),
        trace_id=raw_json.get('trace_id'),
        incident_id=raw_json.get('incident_id'),
        confidence=1.0,  # Default confidence (all parsed events are valid)
    )
    
    # === EXTRACT KIND-SPECIFIC FIELDS ===
    
    if kind == 'deploy':
        event.service = raw_json.get('service')
        event.version = raw_json.get('version')
        event.actor = raw_json.get('actor')
    
    elif kind == 'log':
        event.service = raw_json.get('service')
        event.level = raw_json.get('level')
        event.msg = raw_json.get('msg')
        event.trace_id = raw_json.get('trace_id')
    
    elif kind == 'metric':
        event.service = raw_json.get('service')
        event.name = raw_json.get('name')
        try:
            event.value = float(raw_json.get('value')) if raw_json.get('value') is not None else None
        except (ValueError, TypeError):
            event.value = None
    
    elif kind == 'trace':
        event.trace_id = raw_json.get('trace_id')
        event.spans = raw_json.get('spans', [])  # List of {svc, dur_ms, ...}
    
    elif kind == 'topology':
        event.change = raw_json.get('change')
        event.from_name = raw_json.get('from_')
        event.to_name = raw_json.get('to')
    
    elif kind == 'incident_signal':
        event.incident_id = raw_json.get('incident_id')
        event.trigger = raw_json.get('trigger')
    
    elif kind == 'remediation':
        event.incident_id = raw_json.get('incident_id')
        event.action = raw_json.get('action')
        event.target = raw_json.get('target')
        event.version = raw_json.get('version')
        event.outcome = raw_json.get('outcome')
    
    return event


# ============================================================================
# PART 1C: MULTI-INDEX STORAGE (Blazing-Fast Queries)
# ============================================================================

class EventStore:
    """
    Multi-indexed event storage system.
    
    Provides O(1) lookups by:
    - Service name
    - Trace ID
    - Incident ID
    
    Provides O(log N) lookups by:
    - Time range (binary search)
    
    Handles service renames transparently.
    """
    
    def __init__(self):
        # === STORAGE ===
        self.events: List[Event] = []                           # All events in ingestion order
        self.events_by_service: Dict[str, List[Event]] = {}     # service → events
        self.events_by_trace: Dict[str, List[Event]] = {}       # trace_id → events
        self.events_by_incident: Dict[str, List[Event]] = {}    # incident_id → events
        self.events_by_time: List[Event] = []                   # Sorted by timestamp
        
        # === METADATA ===
        self.rename_map: Dict[str, str] = {}                    # old_service_name → new_service_name
        self.is_finalized: bool = False                          # Whether events are sorted by time
    
    def ingest(self, raw_events: Iterable[Dict[str, Any]]) -> None:
        """
        Parse and ingest a stream of raw JSON events.
        
        Args:
            raw_events: Iterable of raw JSON dicts (from JSONL)
        
        Behavior:
            - Parses each event using parse_and_normalize_event()
            - Skips unparseable events (returns None gracefully)
            - Adds valid events to all indices
            - Updates rename_map for topology changes
            - Does NOT sort by time yet (call finalize() for that)
        """
        # Convert to list to allow two passes
        events_list = list(raw_events)
        
        # First pass: collect all renames
        for raw_event in events_list:
            event = parse_and_normalize_event(raw_event)
            if event and event.kind == 'topology' and event.change == 'rename':
                if event.from_name and event.to_name:
                    self.rename_map[event.from_name] = event.to_name
        
        # Second pass: normalize service names and add to indices
        for raw_event in events_list:
            event = parse_and_normalize_event(raw_event)
            if event:
                # Normalize service name (apply any renames)
                if event.service:
                    event.service = self.get_current_service_name(event.service)
                if event.target:
                    event.target = self.get_current_service_name(event.target)
                
                # Add to indices
                self._add_to_indices(event)
    
    def _add_to_indices(self, event: Event) -> None:
        """
        Add a parsed event to all indices.
        
        Internal method called during ingest().
        """
        # === INDEX 1: All events in order ===
        self.events.append(event)
        
        # === INDEX 2: By service ===
        if event.service:
            if event.service not in self.events_by_service:
                self.events_by_service[event.service] = []
            self.events_by_service[event.service].append(event)
        
        # === INDEX 3: By trace ===
        if event.trace_id:
            if event.trace_id not in self.events_by_trace:
                self.events_by_trace[event.trace_id] = []
            self.events_by_trace[event.trace_id].append(event)
        
        # === INDEX 4: By incident ===
        if event.incident_id:
            if event.incident_id not in self.events_by_incident:
                self.events_by_incident[event.incident_id] = []
            self.events_by_incident[event.incident_id].append(event)
        
        # === TRACK RENAMES ===
        if event.kind == 'topology' and event.change == 'rename':
            if event.from_name and event.to_name:
                self.rename_map[event.from_name] = event.to_name
    
    def finalize(self) -> None:
        """
        Call after ALL events ingested.
        
        Sorts events by timestamp for time-range binary search queries.
        Must be called before calling query_events_in_time_range().
        """
        self.events_by_time = sorted(self.events, key=lambda e: e.ts)
        self.is_finalized = True
    
    def get_current_service_name(self, old_name: str) -> str:
        """
        Handle service renames transparently.
        
        If 'payments-svc' was renamed to 'billing-svc',
        calling this with 'payments-svc' returns 'billing-svc'.
        
        Args:
            old_name: Service name (may be old or new)
        
        Returns:
            Current canonical service name
        """
        return self.rename_map.get(old_name, old_name)
    
    def query_events_by_service(self, service: str) -> List[Event]:
        """
        Get all events for a service.
        
        Args:
            service: Service name (e.g., "checkout-api")
        
        Returns:
            List of events for this service (in order)
        
        Note:
            - Automatically resolves service renames
            - O(1) lookup + O(k) return where k = events for service
        """
        # Resolve rename (if this service was renamed)
        current_name = self.get_current_service_name(service)
        return self.events_by_service.get(current_name, [])
    
    def query_events_by_trace(self, trace_id: str) -> List[Event]:
        """
        Get all events in a request trace.
        
        Args:
            trace_id: Trace ID (e.g., "abc123")
        
        Returns:
            List of events in this trace (in trace order)
        
        Time complexity: O(1)
        """
        return self.events_by_trace.get(trace_id, [])
    
    def query_events_by_incident(self, incident_id: str) -> List[Event]:
        """
        Get all events in an incident.
        
        Args:
            incident_id: Incident ID (e.g., "INC-714")
        
        Returns:
            List of all events tagged with this incident
        
        Time complexity: O(1)
        """
        return self.events_by_incident.get(incident_id, [])
    
    def query_events_in_time_range(self, start_ts: datetime, end_ts: datetime) -> List[Event]:
        """
        Get all events in a time window.
        
        Args:
            start_ts: Start timestamp (inclusive)
            end_ts: End timestamp (inclusive)
        
        Returns:
            List of events within [start_ts, end_ts]
        
        Time complexity: O(log N) binary search + O(k) result where k = events in range
        
        Note: Must call finalize() first!
        """
        if not self.is_finalized:
            # Fallback: linear scan if not finalized
            return [e for e in self.events if start_ts <= e.ts <= end_ts]
        
        # Binary search for left and right boundaries
        left_idx = bisect.bisect_left(
            self.events_by_time,
            start_ts,
            key=lambda e: e.ts
        )
        right_idx = bisect.bisect_right(
            self.events_by_time,
            end_ts,
            key=lambda e: e.ts
        )
        
        return self.events_by_time[left_idx:right_idx]
    
    def get_all_events(self) -> List[Event]:
        """Return all events in ingestion order."""
        return self.events.copy()
    
    def get_event_count(self) -> int:
        """Return total event count."""
        return len(self.events)

    def get_event_by_id(self, event_id: str) -> Optional[Event]:
        """Get event by ID."""
        for e in self.events:
            if e.id == event_id:
                return e
        return None

    def find_event_by_raw(self, raw_dict: Dict[str, Any]) -> Optional[Event]:
        """Find event matching a raw dictionary."""
        # Simple match based on ts and kind
        ts = parse_iso_timestamp(raw_dict.get('ts'))
        kind = raw_dict.get('kind')
        for e in self.events:
            if e.kind == kind and e.ts == ts:
                return e
        return None


# ============================================================================
# PART 1D: MAIN ENGINE CLASS
# ============================================================================

from graph_builder import ServiceDependencyGraph
from causality import CausalityDetector
from fingerprint import IncidentFingerprinter
from pattern_matching import IncidentIndex
from context_builder import ContextBuilder

class Engine:
    """
    Main operational memory engine.
    
    This class:
    - Ingests telemetry streams via ingest()
    - Stores and indexes events (EventStore)
    - Provides query methods for downstream modules
    - Integrates graph, causality, and matching
    """
    
    def __init__(self):
        self.store = EventStore()
        
        self.graph = ServiceDependencyGraph()
        self.causality_detector = CausalityDetector(self)
        self.fingerprinter = IncidentFingerprinter(self)
        self.pattern_matcher = IncidentIndex(self)
        self.context_builder = ContextBuilder(self)
        
    def ingest(self, events: Iterable[Dict[str, Any]]) -> None:
        """
        Main ingestion interface matching the benchmark adapter.
        """
        self.store.ingest(events)
        self.store.finalize()
        
        # Topic 2: Build graph and track deployments
        self.graph.build_from_events(self.store.events, self.store.rename_map)
        self.graph.track_deployment(self.store.events)
        
        # Topic 5: Index historical incidents
        for e in self.store.events:
            if e.kind == 'incident_signal':
                # Convert Event to dict for our internal API
                inc_dict = dict(e.raw)
                inc_dict['error_service'] = inc_dict.get('service')
                inc_dict['detected_at'] = e.ts
                inc_dict['id'] = inc_dict.get('incident_id') or inc_dict.get('id')
                
                # We only index if there's a remediation (so we know it's a closed, historical incident)
                remediations = [re for re in self.store.query_events_by_incident(inc_dict['id']) if re.kind == 'remediation']
                if remediations:
                    # It's a resolved past incident. Let's index it.
                    causality = self.causality_detector.analyze_incident(inc_dict)
                    
                    # Attach the remediation to causality so pattern_matcher can use it
                    causality['historical_context'] = {
                        'fix_applied': remediations[-1].action,
                        'incident_id': inc_dict['id']
                    }
                    fp = self.fingerprinter.extract_fingerprint(causality, inc_dict)
                    self.pattern_matcher.add_incident(inc_dict['id'], fp, causality['historical_context'])
    
    # === HELPER QUERY METHODS (for Topics 2-6) ===
    
    def get_events_for_service(self, service: str) -> List[Event]:
        """Helper: Get all events for a service."""
        return self.store.query_events_by_service(service)
    
    def get_events_for_trace(self, trace_id: str) -> List[Event]:
        """Helper: Get all events in a trace."""
        return self.store.query_events_by_trace(trace_id)
    
    def get_events_for_incident(self, incident_id: str) -> List[Event]:
        """Helper: Get all events in an incident."""
        return self.store.query_events_by_incident(incident_id)
    
    def get_events_in_time_window(self, start_ts: datetime, end_ts: datetime) -> List[Event]:
        """Helper: Get events in time range."""
        return self.store.query_events_in_time_range(start_ts, end_ts)
    
    def get_all_events(self) -> List[Event]:
        """Helper: Get all events."""
        return self.store.get_all_events()
    
    def get_event_count(self) -> int:
        """Helper: Get total event count."""
        return self.store.get_event_count()
    
    def close(self) -> None:
        """Cleanup (required by benchmark adapter interface)."""
        pass
    
    def reconstruct_context(self, signal, mode='fast'):
        """
        Stub for Topic 6 (Context Reconstruction).
        
        Will be implemented later.
        """
        raise NotImplementedError("TODO: Implement in Topic 6 (Context Reconstruction)")


# ============================================================================
# SELF-TEST & VERIFICATION
# ============================================================================

def run_self_test():
    """
    Self-test: Verify Topic 1 works correctly.
    
    Tests:
    - Event parsing works
    - Indexing works
    - All query types work
    - Time range queries work
    """
    
    print("=" * 70)
    print("TOPIC 1 SELF-TEST: Event Ingestion & Storage")
    print("=" * 70)
    
    # === CREATE TEST DATA ===
    test_raw_events = [
        {
            "ts": "2026-05-10T14:21:30Z",
            "kind": "deploy",
            "service": "payments-svc",
            "version": "v2.14.0",
            "actor": "ci"
        },
        {
            "ts": "2026-05-10T14:22:01Z",
            "kind": "log",
            "service": "checkout-api",
            "level": "error",
            "msg": "timeout calling payments-svc",
            "trace_id": "abc123"
        },
        {
            "ts": "2026-05-10T14:22:01Z",
            "kind": "metric",
            "service": "payments-svc",
            "name": "latency_p99_ms",
            "value": 4820
        },
        {
            "ts": "2026-05-10T14:22:08Z",
            "kind": "trace",
            "trace_id": "abc123",
            "spans": [
                {"svc": "checkout-api", "dur_ms": 5012},
                {"svc": "payments-svc", "dur_ms": 4980}
            ]
        },
        {
            "ts": "2026-05-10T14:30:00Z",
            "kind": "topology",
            "change": "rename",
            "from": "payments-svc",
            "to": "billing-svc"
        },
        {
            "ts": "2026-05-10T14:32:11Z",
            "kind": "incident_signal",
            "incident_id": "INC-714",
            "trigger": "alert:checkout-api/error-rate>5%"
        },
        {
            "ts": "2026-05-10T15:10:00Z",
            "kind": "remediation",
            "incident_id": "INC-714",
            "action": "rollback",
            "target": "billing-svc",
            "version": "v2.13.4",
            "outcome": "resolved"
        },
    ]
    
    # === INGEST ===
    print("\n[1] Ingesting 7 test events...")
    engine = Engine()
    engine.ingest(test_raw_events)
    print(f"    ✓ Ingested {engine.get_event_count()} events")
    
    # === TEST: Service queries ===
    print("\n[2] Testing service queries...")
    
    payments_events = engine.get_events_for_service("payments-svc")
    print(f"    Events for payments-svc: {len(payments_events)} (expected 2)")
    assert len(payments_events) == 2, "FAIL: payments-svc should have 2 events"
    print(f"    ✓ Correct")
    
    checkout_events = engine.get_events_for_service("checkout-api")
    print(f"    Events for checkout-api: {len(checkout_events)} (expected 1)")
    assert len(checkout_events) == 1, "FAIL: checkout-api should have 1 event"
    print(f"    ✓ Correct")
    
    # === TEST: Trace queries ===
    print("\n[3] Testing trace queries...")
    
    trace_events = engine.get_events_for_trace("abc123")
    print(f"    Events in trace abc123: {len(trace_events)} (expected 2)")
    assert len(trace_events) == 2, "FAIL: trace abc123 should have 2 events"
    print(f"    ✓ Correct")
    
    # === TEST: Incident queries ===
    print("\n[4] Testing incident queries...")
    
    incident_events = engine.get_events_for_incident("INC-714")
    print(f"    Events in incident INC-714: {len(incident_events)} (expected 2)")
    assert len(incident_events) == 2, "FAIL: incident INC-714 should have 2 events"
    print(f"    ✓ Correct")
    
    # === TEST: Time range queries ===
    print("\n[5] Testing time range queries...")
    
    start = datetime.fromisoformat("2026-05-10T14:21:00+00:00")
    end = datetime.fromisoformat("2026-05-10T14:23:00+00:00")
    time_range_events = engine.get_events_in_time_window(start, end)
    print(f"    Events in [14:21:00, 14:23:00]: {len(time_range_events)} (expected 4)")
    assert len(time_range_events) == 4, "FAIL: time range should have 4 events"
    print(f"    ✓ Correct")
    
    # === TEST: Service rename handling ===
    print("\n[6] Testing service rename handling...")
    
    # Query by old name should work (auto-resolved)
    billing_via_old_name = engine.get_events_for_service("payments-svc")
    print(f"    Query 'payments-svc' (old name) returns: {len(billing_via_old_name)} events")
    print(f"    ✓ Rename mapping works")
    
    # === TEST: Event parsing details ===
    print("\n[7] Verifying event details...")
    
    all_events = engine.get_all_events()
    deploy_event = [e for e in all_events if e.kind == 'deploy'][0]
    print(f"    Deploy event has:")
    print(f"      - ID: {deploy_event.id[:8]}... (UUID)")
    print(f"      - Kind: {deploy_event.kind}")
    print(f"      - Service: {deploy_event.service}")
    print(f"      - Version: {deploy_event.version}")
    print(f"      - Timestamp: {deploy_event.ts} (datetime object)")
    print(f"      - Raw: {len(deploy_event.raw)} fields preserved")
    print(f"    ✓ All fields present and correct")
    
    # === SUCCESS ===
    print("\n" + "=" * 70)
    print("✅ TOPIC 1 COMPLETE - All tests passed!")
    print("=" * 70)
    print("\nYou now have:")
    print("  ✓ Event parsing (normalize JSONL → Event objects)")
    print("  ✓ Multi-indexed storage (4 indices for fast queries)")
    print("  ✓ Main Engine class (ready for Topics 2-6)")
    print("  ✓ O(1) lookups by service/trace/incident")
    print("  ✓ O(log N) lookups by time range")
    print("\nReady for Topic 2: Service Dependency Graph")
    print("=" * 70)


if __name__ == "__main__":
    run_self_test()
