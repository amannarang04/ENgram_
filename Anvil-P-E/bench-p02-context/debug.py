import sys
import os
from harness import _run_one_seed
from generator import GenConfig
from adapters.myteam import EngineAdapter

cfg = GenConfig(seed=42)
adapter = EngineAdapter()
from generator import generate
ds = generate(cfg)
adapter.ingest(ds.train_events)
adapter.ingest(ds.eval_events)
print(f"Rename map: {adapter.engine.graph.rename_map}")
for k in adapter.engine.graph.rename_map.values():
    print(f"Base of {k}: {adapter.engine.graph.get_canonical_name(k)}")
for sig, gt in zip(ds.eval_signals, ds.ground_truth):
    signal = {
        "incident_id": sig["incident_id"],
        "ts":          sig["ts"],
        "trigger":     sig.get("trigger", ""),
        "service":     sig.get("service", ""),
    }
    ctx = adapter.reconstruct_context(signal, mode="fast")
    print(f"\nEVAL INCIDENT: {sig['incident_id']} (Family {gt['family']})")
    for m in ctx.get('similar_past_incidents', [])[:5]:
        print(f"  MATCH: {m['incident_id']} - score: {m['similarity']}")
        print(f"    rationale: {m['rationale']}")
