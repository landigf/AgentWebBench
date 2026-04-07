#!/usr/bin/env python3
"""Convert Playwright HAR recordings into TraceSession objects.

Usage:
    python har_to_trace.py --input human_news.har human_api.har --output data/releases/human-baseline-v1/

Each HAR file becomes one TraceSession with agent_type=HUMAN.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from trace_schema import AccessMode, AgentType, TraceFile, TraceRequest, TraceSession


def har_to_session(har_path: Path) -> TraceSession:
    """Parse a HAR file into a TraceSession."""
    with har_path.open() as f:
        har = json.load(f)

    entries = har.get("log", {}).get("entries", [])
    if not entries:
        raise ValueError(f"No entries in {har_path}")

    task_id = har_path.stem.replace("human_", "")
    session_id = f"human_{task_id}_0"

    requests: list[TraceRequest] = []
    for entry in entries:
        started = entry.get("startedDateTime", "")
        try:
            dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            ts_us = int(dt.timestamp() * 1_000_000)
        except (ValueError, AttributeError):
            ts_us = 0

        resp = entry.get("response", {})
        content = resp.get("content", {})
        content_type = content.get("mimeType", "").split(";")[0].strip()
        body_size = resp.get("bodySize", 0)
        if body_size <= 0:
            body_size = content.get("size", 0)

        req = entry.get("request", {})
        requests.append(TraceRequest(
            timestamp_us=ts_us,
            url=req.get("url", ""),
            method=req.get("method", "GET"),
            status=resp.get("status", 0),
            response_size_bytes=max(0, body_size),
            content_type=content_type,
            latency_ms=entry.get("time", 0.0),
            session_id=session_id,
            task_id=task_id,
            access_mode=AccessMode.SCRAPING,
            agent_type=AgentType.HUMAN,
            cache_key=req.get("url", ""),
            object_size_bytes=max(0, body_size),
        ))

    requests.sort(key=lambda r: r.timestamp_us)
    start_us = requests[0].timestamp_us if requests else 0
    end_us = requests[-1].timestamp_us if requests else 0

    return TraceSession(
        session_id=session_id,
        task_id=task_id,
        task_name=f"human-{task_id}",
        agent_type=AgentType.HUMAN,
        access_mode=AccessMode.SCRAPING,
        start_time_us=start_us,
        end_time_us=end_us,
        requests=requests,
        metadata={
            "source": "har-recording",
            "har_file": har_path.name,
            "collection_region": "local",
            "collection_provider": "manual",
        },
    )


def main():
    parser = argparse.ArgumentParser(description="Convert HAR files to AgentWebBench trace format")
    parser.add_argument("--input", nargs="+", required=True, help="HAR file(s) to convert")
    parser.add_argument("--output", required=True, help="Output directory for traces")
    args = parser.parse_args()

    sessions: list[TraceSession] = []
    for har_file in args.input:
        path = Path(har_file)
        if not path.exists():
            print(f"  Warning: {har_file} not found, skipping")
            continue
        session = har_to_session(path)
        sessions.append(session)
        print(f"  {path.name}: {session.total_requests} requests, {session.total_bytes} bytes")

    if not sessions:
        print("No sessions converted.")
        return

    trace = TraceFile(generator="har-to-trace", sessions=sessions)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    trace.save(out_dir / "traces.json")
    trace.to_cache_sim_csv(out_dir / "cache_trace.csv")
    trace.to_access_log_jsonl(out_dir / "access_log.jsonl")

    summary = {
        "source": "human-baseline",
        "sessions": len(sessions),
        "total_requests": trace.total_requests,
        "total_bytes": sum(s.total_bytes for s in sessions),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\n  Saved {len(sessions)} human sessions to {args.output}")


if __name__ == "__main__":
    main()
