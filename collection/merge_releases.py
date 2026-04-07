#!/usr/bin/env python3
"""Merge regional trace collections into a unified browseruse-live-v2 release.

Usage:
    python merge_releases.py \
        --input ./gcp-collection/us-central ./gcp-collection/eu-west ./gcp-collection/asia-southeast \
               ./gcp-collection/us-west ./gcp-collection/sa-east \
               ./local-collection/ \
               ./human-baseline/ \
        --output ../data/releases/browseruse-live-v2/

Each input directory is expected to contain subdirectories like:
    scripted-random/<task-id>/traces.json
    llm-agent/<task-id>/traces.json
    (or flat: <task-id>/traces.json)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from trace_schema import TraceFile, TraceSession


def discover_trace_files(input_dir: Path) -> list[Path]:
    """Find all traces.json files under a directory."""
    return sorted(input_dir.rglob("traces.json"))


def load_sessions(trace_path: Path) -> list[TraceSession]:
    """Load sessions from a traces.json file."""
    tf = TraceFile.load(trace_path)
    return tf.sessions


def merge_sessions_by_task(
    input_dirs: list[Path],
) -> dict[str, list[TraceSession]]:
    """Merge all sessions grouped by task_id."""
    by_task: dict[str, list[TraceSession]] = defaultdict(list)
    seen_session_ids: set[str] = set()

    for input_dir in input_dirs:
        trace_files = discover_trace_files(input_dir)
        if not trace_files:
            print(f"  Warning: no traces.json found under {input_dir}")
            continue

        for tf_path in trace_files:
            sessions = load_sessions(tf_path)
            for session in sessions:
                # Deduplicate by session_id
                if session.session_id in seen_session_ids:
                    continue
                seen_session_ids.add(session.session_id)
                task_id = session.task_id or "unknown"
                by_task[task_id].append(session)

    return dict(by_task)


def build_manifest(
    release: str,
    by_task: dict[str, list[TraceSession]],
) -> dict:
    """Build manifest.json for the merged release."""
    total_sessions = 0
    total_requests = 0
    total_bytes = 0
    regions: set[str] = set()
    drivers: set[str] = set()
    tasks = []

    for task_id, sessions in sorted(by_task.items()):
        task_reqs = sum(s.total_requests for s in sessions)
        task_bytes = sum(s.total_bytes for s in sessions)
        total_sessions += len(sessions)
        total_requests += task_reqs
        total_bytes += task_bytes

        for s in sessions:
            regions.add(s.metadata.get("collection_region", "unknown"))
            driver = s.metadata.get("live_driver", s.metadata.get("source", "unknown"))
            drivers.add(driver)

        tasks.append({
            "task_id": task_id,
            "sessions": len(sessions),
            "total_requests": task_reqs,
            "total_bytes": task_bytes,
            "avg_requests_per_session": task_reqs / len(sessions) if sessions else 0,
        })

    return {
        "release": release,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tasks": tasks,
        "total_sessions": total_sessions,
        "total_requests": total_requests,
        "total_bytes": total_bytes,
        "regions": sorted(regions),
        "drivers": sorted(drivers),
        "task_count": len(tasks),
    }


def save_merged_release(
    by_task: dict[str, list[TraceSession]],
    output_dir: Path,
    release: str,
):
    """Save merged traces per task, plus manifest."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for task_id, sessions in sorted(by_task.items()):
        task_dir = output_dir / "scraping" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        tf = TraceFile(
            generator=f"merge-releases-{release}",
            sessions=sessions,
        )
        tf.save(task_dir / "traces.json")
        tf.to_cache_sim_csv(task_dir / "cache_trace.csv")
        tf.to_access_log_jsonl(task_dir / "access_log.jsonl")

        summary = {
            "task_id": task_id,
            "task_name": sessions[0].task_name if sessions else task_id,
            "mode": "scraping",
            "repeats": len(sessions),
            "total_requests": tf.total_requests,
            "avg_requests_per_run": tf.total_requests / len(sessions) if sessions else 0,
            "avg_bytes_per_run": sum(s.total_bytes for s in sessions) / len(sessions) if sessions else 0,
            "sessions": [
                {
                    "session_id": s.session_id,
                    "total_requests": s.total_requests,
                    "total_bytes": s.total_bytes,
                    "unique_urls": s.unique_urls,
                    "duration_ms": s.duration_ms,
                    "metadata": s.metadata,
                }
                for s in sessions
            ],
        }
        (task_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    # Also save by-region view (symlink-free, just metadata index)
    manifest = build_manifest(release, by_task)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"\n  Merged release: {release}")
    print(f"  Tasks: {manifest['task_count']}")
    print(f"  Sessions: {manifest['total_sessions']}")
    print(f"  Requests: {manifest['total_requests']}")
    print(f"  Bytes: {manifest['total_bytes'] / (1024*1024):.1f} MiB")
    print(f"  Regions: {', '.join(manifest['regions'])}")
    print(f"  Drivers: {', '.join(manifest['drivers'])}")
    print(f"  Output: {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="Merge regional traces into unified release")
    parser.add_argument("--input", nargs="+", required=True, help="Input directories containing traces")
    parser.add_argument("--output", required=True, help="Output directory for merged release")
    parser.add_argument("--release", default="browseruse-live-v2", help="Release name")
    args = parser.parse_args()

    input_dirs = [Path(d) for d in args.input]
    missing = [d for d in input_dirs if not d.exists()]
    if missing:
        print(f"  Warning: missing input dirs: {[str(d) for d in missing]}")
        input_dirs = [d for d in input_dirs if d.exists()]

    if not input_dirs:
        print("No valid input directories.")
        return

    by_task = merge_sessions_by_task(input_dirs)
    if not by_task:
        print("No sessions found in any input directory.")
        return

    save_merged_release(by_task, Path(args.output), args.release)


if __name__ == "__main__":
    main()
