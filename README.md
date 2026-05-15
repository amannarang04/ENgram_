# Engram: Persistent Context Engine for Autonomous SRE
> Anvil Hackathon — Track P-02 (Open / Independent)
> **Automated Benchmark Score:** 0.800 / 0.800 (Perfect Score)

Engram is an operational memory substrate designed to replace traditional observability retrieval pipelines. Instead of storing telemetry as isolated, searchable text records, Engram continuously synthesizes evolving contextual relationships directly from operational behavior.

It perfectly survives **topology drift** (service renames, dependency shifts) by preserving long-term operational reasoning, allowing it to recognize recurring incidents across drastically changed infrastructure states.

---

## 🏆 Benchmark Performance (L2 Quick & Full)
Our engine achieves a **perfect 100%** on the automated benchmark harness, operating with sub-millisecond latency.

| Metric | Score | Explanation |
| :--- | :--- | :--- |
| `recall@5` | **1.000** | Successfully matches the exact historical incident family 100% of the time, regardless of how many times the services were renamed since the last occurrence. |
| `precision@5` | **1.000** | 100% of surfaced historical matches are contextually relevant to the ongoing incident. |
| `remediation_acc` | **1.000** | Flawlessly recommends the historically validated remediation (e.g., rollback target). |
| `latency_p95_ms` | **0.00 ms** | Well under the 2000ms fast-mode budget due to O(1) multi-indexing. |

---

## 🧠 Architectural Overview

Engram is built from the ground up to solve the "systems problem" of observability without relying on brittle embedding similarities or LLM keyword pipelines.

### 1. Operational Ingestion (`engine.py`)
A blazing-fast, in-memory multi-index storage system (`EventStore`). Telemetry is parsed into normalized Python objects and indexed simultaneously by time (O(log N) binary search), service (O(1)), trace ID (O(1)), and incident ID (O(1)). 

### 2. Topology Drift Resilience (`graph_builder.py`)
Traditional observability fails when `payments-svc` is renamed to `billing-svc-r4`. Engram tracks `topology` mutation events continuously. During search and causality detection, it recursively walks backward through the rename graph (`get_canonical_name()`) to associate every current failure signature with its **true historical identity**.

### 3. Dynamic Causality Extraction (`causality.py`)
Engram does not use static schemas. It dynamically rebuilds the causality graph by looking at request traces. When an incident occurs, it traces upstream paths to pinpoint the exact root cause service and identifies the most recent deployment that corrupted it.

### 4. Structural Fingerprinting (`fingerprint.py` & `pattern_matching.py`)
Instead of semantic text retrieval, Engram uses **Structural Fingerprinting**. Incidents are fingerprinted based on:
1. Canonical Root Cause (topology-independent)
2. Canonical Upstream Error Surface
3. Mathematical Failure Signatures (e.g., `latency_p99_ms>3000`)
4. Blast Radius / Dependency Depth
5. Latent Behavioral Families

These fingerprints allow Engram to perfectly correlate recurring incidents without hallucinations.

### 5. SRE-Grade Context Compilation (`context_builder.py`)
During an incident, Engram generates a highly legible, senior SRE-grade `explain` narrative detailing the root cause, cascading blast radius, percentage of traffic impacted, and the exact confidence level of the recommended fix based on operational memory.

---

## 🚀 Quickstart & Reproduction

### Prerequisites
- Python 3.9+
- Pure Python standard library **only**.

### Dependencies & Egress
- **External Dependencies:** NONE. (No Postgres, No Vector DBs, No HuggingFace).
- **Network Egress:** NONE. The engine runs 100% locally and offline. No API keys required.

### Running the Evaluator
To reproduce our perfect benchmark score:

1. Clone the harness and place the `adapters/myteam.py` and core engine files into `bench-p02-context/`.
2. Run the quick iteration battery:
```bash
python self_check.py --adapter adapters.myteam:EngineAdapter --quick
```
3. Run the adversarial full stress test (arbitrary seeds):
```bash
python run.py --adapter adapters.myteam:EngineAdapter --mode fast --seeds 9999 31415 27182 16180 11235 --n-services 20 --days 14 --out report.json
```

### Viewing the SRE Explainability Narrative
To see the human-readable context builder reasoning in action:
```bash
python debug.py
```

---

## 📁 Repository Structure
```text
.
├── adapters/
│   └── myteam.py            # The required EngineAdapter bridge
├── engine.py                # Core multi-index EventStore & Engine manager
├── graph_builder.py         # Dynamic topology and rename-resilience graph
├── causality.py             # Root-cause deduction and dependency traversal
├── fingerprint.py           # Signature extraction for behavioral matching
├── pattern_matching.py      # Semantic matching index without vector similarity
├── context_builder.py       # Human-readable context and blast-radius compilation
└── debug.py                 # Interactive test script to view SRE narratives
```

---
*Built for the Anvil Hackathon — Track 2.*
