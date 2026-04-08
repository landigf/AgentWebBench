#!/usr/bin/env python3
"""Convert AgentWebBench traces to CacheRegime Event format.

This adapter bridges AgentWebBench (browser-mediated agent traffic)
with CacheRegime (cache policy regime characterization), enabling:
1. Direct replay of agent traces through CacheRegime's 6-policy simulator
2. Workload feature computation (one_hit_ratio, size_cv, etc.)
3. Regime classification of agent workloads
4. Mixed human+agent replay by merging with production CDN traces

Usage:
    python convert.py \
        --input ../../asl-project/data/releases/browseruse-live-v3/ \
        --output ./cacheregime-traces/ \
        --format csv    # or 'events' for Python pickle

    # Then in CacheRegime:
    cd /path/to/CacheRegime
    python tools/fast27_realistic_panel_v2.py --external-ai-csv ./cacheregime-traces/agentwebbench.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


def stable_u64(text: str) -> int:
    """Hash a string to a stable uint64 — same function as CacheRegime."""
    return int.from_bytes(
        hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "little"
    )


@dataclass
class CacheRegimeEvent:
    """Matches CacheRegime's Event dataclass exactly."""
    timestamp: float
    obj_id: int
    obj_size: int
    source: str          # "human" or "ai"
    session_id: str
    source_label: str    # e.g., "agentwebbench:news-aggregation"
    trace_name: str      # "agentwebbench"


def load_agentwebbench_traces(release_dir: Path) -> list[dict]:
    """Load all requests from an AgentWebBench release."""
    all_requests = []
    for tf_path in sorted(release_dir.rglob("traces.json")):
        with tf_path.open() as f:
            data = json.load(f)
        for session in data.get("sessions", []):
            task_id = session.get("task_id", "unknown")
            agent_type = session.get("agent_type", "unknown")
            session_id = session.get("session_id", "")
            for req in session.get("requests", []):
                all_requests.append({
                    "timestamp_us": req.get("timestamp_us", 0),
                    "url": req.get("url", req.get("cache_key", "")),
                    "object_size_bytes": req.get("object_size_bytes", 0) or req.get("response_size_bytes", 0),
                    "session_id": session_id,
                    "task_id": task_id,
                    "agent_type": agent_type,
                })
    return all_requests


def convert_to_events(requests: list[dict], trace_name: str = "agentwebbench") -> list[CacheRegimeEvent]:
    """Convert AgentWebBench requests to CacheRegime Events."""
    events = []
    for req in requests:
        url = req["url"]
        if not url:
            continue
        size = max(1, req["object_size_bytes"])  # CacheRegime clamps to 1
        agent_type = req.get("agent_type", "unknown")
        source = "human" if agent_type == "human" else "ai"
        source_label = f"{trace_name}:{req.get('task_id', 'unknown')}"

        events.append(CacheRegimeEvent(
            timestamp=req["timestamp_us"] / 1_000_000,  # us -> seconds
            obj_id=stable_u64(url),
            obj_size=size,
            source=source,
            session_id=req["session_id"],
            source_label=source_label,
            trace_name=trace_name,
        ))
    return events


def compute_workload_features(events: list[CacheRegimeEvent]) -> dict:
    """Compute CacheRegime workload features from events.

    These features are used by CacheRegime's selector to predict
    the optimal cache policy family.
    """
    if not events:
        return {}

    # Count object accesses
    obj_counts: dict[int, int] = defaultdict(int)
    obj_sizes: dict[int, int] = {}
    for e in events:
        obj_counts[e.obj_id] += 1
        obj_sizes[e.obj_id] = e.obj_size

    total_requests = len(events)
    unique_objects = len(obj_counts)
    one_hit_objects = sum(1 for c in obj_counts.values() if c == 1)

    sizes = list(obj_sizes.values())
    mean_size = sum(sizes) / len(sizes) if sizes else 0
    variance = sum((s - mean_size) ** 2 for s in sizes) / len(sizes) if sizes else 0
    stdev = variance ** 0.5
    size_cv = stdev / mean_size if mean_size > 0 else 0

    # Prefix features (first 2000 requests)
    prefix = events[:2000]
    prefix_seen: set[int] = set()
    prefix_revisits = 0
    for e in prefix:
        if e.obj_id in prefix_seen:
            prefix_revisits += 1
        prefix_seen.add(e.obj_id)

    return {
        "one_hit_object_fraction": one_hit_objects / unique_objects if unique_objects else 0,
        "unique_request_fraction": unique_objects / total_requests if total_requests else 0,
        "prefix_unique_request_fraction": len(prefix_seen) / len(prefix) if prefix else 0,
        "prefix_revisit_request_fraction": prefix_revisits / len(prefix) if prefix else 0,
        "mean_object_size": mean_size,
        "size_cv": size_cv,
        "total_requests": total_requests,
        "unique_objects": unique_objects,
        "total_bytes": sum(e.obj_size for e in events),
    }


def predict_regime(features: dict) -> str:
    """Predict cache policy regime using CacheRegime's decision tree.

    Thresholds from CacheRegime FAST '27 paper:
    - one_hit_object_fraction > 0.8947 → WTinyLFU family
    - size_cv > 1.8562 → GDSF family
    - else → S3FIFO family
    """
    ohr = features.get("one_hit_object_fraction", 0)
    scv = features.get("size_cv", 0)

    if ohr > 0.8947:
        return "WTinyLFU"
    elif scv > 1.8562:
        return "GDSF"
    else:
        return "S3FIFO"


def export_csv(events: list[CacheRegimeEvent], output_path: Path):
    """Export events as CSV compatible with CacheRegime's load_weblinx_events()."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "object_id", "object_size", "session_id", "source_label"])
        for e in events:
            writer.writerow([e.timestamp, e.obj_id, e.obj_size, e.session_id, e.source_label])


def main():
    parser = argparse.ArgumentParser(description="Convert AgentWebBench → CacheRegime format")
    parser.add_argument("--input", required=True, help="AgentWebBench release directory")
    parser.add_argument("--output", default="./cacheregime-traces", help="Output directory")
    parser.add_argument("--trace-name", default="agentwebbench", help="Trace name for CacheRegime")
    args = parser.parse_args()

    release_dir = Path(args.input)
    output_dir = Path(args.output)

    print(f"Loading AgentWebBench traces from {release_dir}...")
    requests = load_agentwebbench_traces(release_dir)
    print(f"  {len(requests)} requests loaded")

    print("Converting to CacheRegime Events...")
    events = convert_to_events(requests, trace_name=args.trace_name)
    print(f"  {len(events)} events converted")

    print("\nWorkload features:")
    features = compute_workload_features(events)
    for k, v in features.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

    regime = predict_regime(features)
    print(f"\n  Predicted CacheRegime policy family: {regime}")

    csv_path = output_dir / "agentwebbench.csv"
    export_csv(events, csv_path)
    print(f"\n  Exported to {csv_path}")

    # Also export features
    features_path = output_dir / "workload_features.json"
    features["predicted_regime"] = regime
    features_path.parent.mkdir(parents=True, exist_ok=True)
    features_path.write_text(json.dumps(features, indent=2) + "\n")
    print(f"  Features saved to {features_path}")


if __name__ == "__main__":
    main()
