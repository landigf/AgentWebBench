#!/usr/bin/env python3
"""Validate a merged release for quality issues before paper submission.

Inspired by ELT-Bench-Verified (Zanoli et al., 2026): benchmark quality issues
can systematically skew results. This script catches common problems.

Usage:
    python validate_release.py --release browseruse-live-v2
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from trace_schema import TraceFile

ROOT = Path(__file__).resolve().parents[1]
RELEASES_DIR = ROOT / "data"


class ValidationReport:
    def __init__(self):
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.stats: dict[str, any] = {}

    def warn(self, msg: str):
        self.warnings.append(msg)
        print(f"  WARNING: {msg}")

    def error(self, msg: str):
        self.errors.append(msg)
        print(f"  ERROR: {msg}")

    def summary(self):
        print(f"\n  === Validation Summary ===")
        print(f"  Errors: {len(self.errors)}")
        print(f"  Warnings: {len(self.warnings)}")
        for key, val in sorted(self.stats.items()):
            print(f"  {key}: {val}")
        if not self.errors and not self.warnings:
            print("  All checks passed.")
        return len(self.errors) == 0


def validate_release(release: str) -> bool:
    release_dir = RELEASES_DIR / release
    if not release_dir.exists():
        print(f"Release directory not found: {release_dir}")
        return False

    report = ValidationReport()

    # Load all trace files
    trace_paths = sorted(release_dir.rglob("traces.json"))
    if not trace_paths:
        report.error("No traces.json files found")
        return report.summary()

    all_sessions = []
    sessions_by_task: dict[str, list] = defaultdict(list)
    sessions_by_region: dict[str, list] = defaultdict(list)
    sessions_by_driver: dict[str, list] = defaultdict(list)

    for tp in trace_paths:
        tf = TraceFile.load(tp)
        for session in tf.sessions:
            all_sessions.append(session)
            sessions_by_task[session.task_id].append(session)
            region = session.metadata.get("collection_region", "unknown")
            sessions_by_region[region].append(session)
            driver = session.metadata.get("live_driver", session.metadata.get("source", "unknown"))
            sessions_by_driver[driver].append(session)

    report.stats["total_sessions"] = len(all_sessions)
    report.stats["tasks"] = len(sessions_by_task)
    report.stats["regions"] = sorted(sessions_by_region.keys())
    report.stats["drivers"] = sorted(sessions_by_driver.keys())

    # --- Check 1: Degenerate sessions (0 requests) ---
    degenerate = [s for s in all_sessions if s.total_requests == 0]
    if degenerate:
        report.warn(f"{len(degenerate)} sessions have 0 requests (degenerate)")
        for s in degenerate[:5]:
            report.warn(f"  -> {s.session_id} (task={s.task_id}, region={s.metadata.get('collection_region', '?')})")

    # --- Check 2: Very small sessions (< 5 requests, likely bot-blocked) ---
    tiny = [s for s in all_sessions if 0 < s.total_requests < 5]
    if tiny:
        report.warn(f"{len(tiny)} sessions have < 5 requests (possibly bot-blocked)")

    # --- Check 3: High error-rate sessions (> 50% non-2xx) ---
    for session in all_sessions:
        if session.total_requests == 0:
            continue
        error_count = sum(1 for r in session.requests if r.status >= 400)
        error_rate = error_count / session.total_requests
        if error_rate > 0.5:
            report.warn(
                f"Session {session.session_id}: {error_rate:.0%} error rate "
                f"({error_count}/{session.total_requests} requests)"
            )

    # --- Check 4: Task coverage across regions ---
    for task_id in sorted(sessions_by_task.keys()):
        task_regions = {
            s.metadata.get("collection_region", "unknown")
            for s in sessions_by_task[task_id]
        }
        all_regions = set(sessions_by_region.keys())
        missing = all_regions - task_regions
        if missing and len(all_regions) > 1:
            report.warn(f"Task {task_id} missing from regions: {sorted(missing)}")

    # --- Check 5: Minimum repeats per task ---
    for task_id, sessions in sorted(sessions_by_task.items()):
        if len(sessions) < 10:
            report.warn(f"Task {task_id}: only {len(sessions)} sessions (target: 20+)")

    # --- Check 6: Request volume consistency ---
    for task_id, sessions in sorted(sessions_by_task.items()):
        req_counts = [s.total_requests for s in sessions if s.total_requests > 0]
        if len(req_counts) < 2:
            continue
        mean_reqs = sum(req_counts) / len(req_counts)
        max_reqs = max(req_counts)
        min_reqs = min(req_counts)
        if max_reqs > 10 * min_reqs and min_reqs > 0:
            report.warn(
                f"Task {task_id}: high request volume variance "
                f"(min={min_reqs}, max={max_reqs}, mean={mean_reqs:.0f})"
            )

    # --- Check 7: Navigation errors ---
    total_nav_errors = 0
    for session in all_sessions:
        nav_errors = session.metadata.get("navigation_errors", [])
        total_nav_errors += len(nav_errors)
    if total_nav_errors > 0:
        report.stats["navigation_errors"] = total_nav_errors
        if total_nav_errors > len(all_sessions) * 0.1:
            report.warn(f"High navigation error rate: {total_nav_errors} errors across {len(all_sessions)} sessions")

    # --- Check 8: Session ID uniqueness ---
    session_ids = [s.session_id for s in all_sessions]
    if len(session_ids) != len(set(session_ids)):
        dupes = len(session_ids) - len(set(session_ids))
        report.error(f"{dupes} duplicate session IDs found")

    # --- Per-task summary table ---
    print("\n  === Per-Task Summary ===")
    print(f"  {'Task':<30} {'Sessions':>8} {'Avg Reqs':>10} {'Avg MiB':>10} {'Regions':>10}")
    print(f"  {'-'*30} {'-'*8} {'-'*10} {'-'*10} {'-'*10}")
    for task_id in sorted(sessions_by_task.keys()):
        sessions = sessions_by_task[task_id]
        avg_reqs = sum(s.total_requests for s in sessions) / len(sessions)
        avg_mib = sum(s.total_bytes for s in sessions) / len(sessions) / (1024 * 1024)
        n_regions = len({s.metadata.get("collection_region", "?") for s in sessions})
        print(f"  {task_id:<30} {len(sessions):>8} {avg_reqs:>10.0f} {avg_mib:>10.2f} {n_regions:>10}")

    return report.summary()


def main():
    parser = argparse.ArgumentParser(description="Validate a benchmark release")
    parser.add_argument("--release", default="browseruse-live-v2", help="Release name")
    args = parser.parse_args()

    success = validate_release(args.release)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
