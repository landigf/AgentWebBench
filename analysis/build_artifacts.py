#!/usr/bin/env python3
"""Regenerate paper-ready artifacts from a checked-in benchmark release."""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
PAPER_DIR = Path(__file__).resolve().parent
ASL_RELEASES = ROOT / "data"
CACHE_SIM_DIR = ROOT / "cache-sim"
PAPER_FIGURES = PAPER_DIR / "figures"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def session_unique_ratio(session: dict) -> float:
    total_requests = session.get("total_requests", 0) or 0
    if total_requests <= 0:
        return 0.0
    return float(session.get("unique_urls", 0)) / total_requests


def load_task_summaries(release_dir: Path) -> list[dict]:
    summaries: list[dict] = []
    for summary_path in sorted(release_dir.glob("*/*/summary.json")):
        with summary_path.open() as f:
            summaries.append(json.load(f))
    if not summaries:
        for summary_path in sorted(release_dir.glob("*/summary.json")):
            with summary_path.open() as f:
                summaries.append(json.load(f))
    if not summaries:
        raise FileNotFoundError(f"No summary.json files found under {release_dir}")
    return summaries


def load_trace_sessions(release_dir: Path) -> list[dict]:
    sessions: list[dict] = []
    trace_paths = sorted(release_dir.glob("*/*/traces.json")) or sorted(release_dir.glob("*/traces.json"))
    if not trace_paths:
        raise FileNotFoundError(f"No traces.json files found under {release_dir}")
    for trace_path in trace_paths:
        with trace_path.open() as f:
            data = json.load(f)
        if isinstance(data, dict) and "sessions" in data:
            sessions.extend(data["sessions"])
        elif isinstance(data, list):
            sessions.extend(data)
        else:
            sessions.append(data)
    return sessions


def build_manifest_from_summaries(release: str, release_dir: Path, summaries: list[dict]) -> dict:
    tasks = []
    total_requests = 0
    total_bytes = 0
    total_sessions = 0
    collection_methods = set()

    for summary in summaries:
        sessions = summary.get("sessions", [])
        total_requests += int(summary.get("total_requests", 0))
        total_bytes += sum(int(session.get("total_bytes", 0)) for session in sessions)
        total_sessions += len(sessions)
        for session in sessions:
            metadata = session.get("metadata", {})
            live_driver = metadata.get("live_driver") or summary.get("live_driver")
            if live_driver:
                collection_methods.add(f"BrowserUse live {live_driver} baseline")
        tasks.append(
            {
                "task_id": summary["task_id"],
                "task_name": summary["task_name"],
                "repeats": len(sessions),
                "avg_requests_per_run": summary.get("avg_requests_per_run", 0),
                "avg_bytes_per_run": summary.get("avg_bytes_per_run", 0),
                "live_driver": summary.get("live_driver"),
            }
        )

    if not collection_methods:
        collection_methods.add("BrowserUse live release")

    latest_mtime = max(path.stat().st_mtime for path in release_dir.rglob("summary.json"))
    manifest = {
        "release": release,
        "collected_on": datetime.fromtimestamp(latest_mtime, tz=timezone.utc).date().isoformat(),
        "collection_method": ", ".join(sorted(collection_methods)),
        "tasks": tasks,
        "total_requests": total_requests,
        "total_bytes": total_bytes,
        "total_sessions": total_sessions,
    }
    return manifest


def load_or_build_manifest(release: str, release_dir: Path, summaries: list[dict]) -> dict:
    manifest_path = release_dir / "manifest.json"
    if manifest_path.exists():
        with manifest_path.open() as f:
            return json.load(f)
    manifest = build_manifest_from_summaries(release, release_dir, summaries)
    with manifest_path.open("w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return manifest


def mean_ci95(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], 0.0
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    ci = 1.96 * stdev / math.sqrt(len(values))
    return mean, ci


def task_stats_from_summaries(summaries: list[dict]) -> list[dict]:
    rows = []
    for summary in summaries:
        sessions = summary.get("sessions", [])
        reqs = [float(s.get("total_requests", 0)) for s in sessions]
        mib = [float(s.get("total_bytes", 0)) / (1024 * 1024) for s in sessions]
        unique_ratios = [session_unique_ratio(s) for s in sessions]
        durations = [float(s.get("duration_ms", 0)) for s in sessions]
        req_mean, req_ci = mean_ci95(reqs)
        mib_mean, mib_ci = mean_ci95(mib)
        rows.append(
            {
                "task_id": summary["task_id"],
                "task_name": summary["task_name"],
                "repeats": len(sessions),
                "requests_mean": req_mean,
                "requests_ci95": req_ci,
                "mib_mean": mib_mean,
                "mib_ci95": mib_ci,
                "unique_ratio_mean": statistics.mean(unique_ratios) if unique_ratios else 0.0,
                "unique_ratio_median": statistics.median(unique_ratios) if unique_ratios else 0.0,
                "duration_mean_ms": statistics.mean(durations) if durations else 0.0,
            }
        )
    return rows


def content_type_stats(trace_sessions: list[dict]) -> tuple[dict[str, int], int]:
    ctype_bytes: dict[str, int] = defaultdict(int)
    total_bytes = 0
    for session in trace_sessions:
        for request in session.get("requests", []):
            content_type = (request.get("content_type") or "unknown").split(";")[0].strip().lower()
            size = int(request.get("response_size_bytes", 0) or 0)
            ctype_bytes[content_type] += size
            total_bytes += size
    return dict(ctype_bytes), total_bytes


def combine_cache_traces(release_dir: Path, output_csv: Path) -> None:
    traces = sorted(release_dir.glob("*/*/cache_trace.csv")) or sorted(release_dir.glob("*/cache_trace.csv"))
    if not traces:
        raise FileNotFoundError(f"No cache_trace.csv files found under {release_dir}")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    with output_csv.open("w", newline="") as out_f:
        for trace_path in traces:
            with trace_path.open(newline="") as in_f:
                reader = csv.DictReader(in_f)
                if writer is None:
                    writer = csv.DictWriter(out_f, fieldnames=reader.fieldnames)
                    writer.writeheader()
                for row in reader:
                    writer.writerow(row)


def copy_figure(src: Path, dst_name: str) -> None:
    PAPER_FIGURES.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, PAPER_FIGURES / dst_name)


def plot_live_baseline(task_stats: list[dict], output_path: Path) -> None:
    PAPER_FIGURES.mkdir(parents=True, exist_ok=True)
    labels = [row["task_id"].replace("-1", "").replace("-", "\n") for row in task_stats]
    x = list(range(len(task_stats)))
    req_means = [row["requests_mean"] for row in task_stats]
    req_ci = [row["requests_ci95"] for row in task_stats]
    mib_means = [row["mib_mean"] for row in task_stats]
    mib_ci = [row["mib_ci95"] for row in task_stats]

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4))

    axes[0].bar(x, req_means, color="#355C7D", yerr=req_ci, capsize=4)
    axes[0].set_xticks(x, labels)
    axes[0].set_ylabel("Requests / run")
    axes[0].set_title("Request volume")
    axes[0].grid(axis="y", alpha=0.25)

    axes[1].bar(x, mib_means, color="#C06C84", yerr=mib_ci, capsize=4)
    axes[1].set_xticks(x, labels)
    axes[1].set_ylabel("Transferred MiB / run")
    axes[1].set_title("Transferred bytes")
    axes[1].grid(axis="y", alpha=0.25)

    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def plot_content_type_mix(ctype_bytes: dict[str, int], total_bytes: int, output_path: Path) -> None:
    PAPER_FIGURES.mkdir(parents=True, exist_ok=True)
    top = sorted(ctype_bytes.items(), key=lambda kv: kv[1], reverse=True)[:8]
    labels = [k if len(k) <= 26 else k[:23] + "..." for k, _ in top]
    values = [v / total_bytes * 100 if total_bytes else 0.0 for _, v in top]

    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.barh(labels[::-1], values[::-1], color="#6C5B7B")
    ax.set_xlabel("Byte share (%)")
    ax.set_title("Top content types by transferred bytes")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def plot_geo_comparison(trace_sessions: list[dict], output_path: Path) -> None:
    """Plot request volume and latency by region for each task."""
    PAPER_FIGURES.mkdir(parents=True, exist_ok=True)

    # Group sessions by (task, region)
    by_task_region: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for session in trace_sessions:
        task_id = session.get("task_id", "unknown")
        region = (session.get("metadata", {}).get("collection_region") or "unknown")
        if region == "unknown":
            continue
        by_task_region[task_id][region].append(session)

    if not by_task_region:
        return

    tasks = sorted(by_task_region.keys())
    regions = sorted({r for regions in by_task_region.values() for r in regions})
    if len(regions) < 2:
        return

    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    x = list(range(len(tasks)))
    width = 0.8 / len(regions)
    colors = plt.cm.Set2(range(len(regions)))

    for i, region in enumerate(regions):
        req_means = []
        lat_means = []
        for task in tasks:
            sessions = by_task_region[task].get(region, [])
            reqs = [len(s.get("requests", [])) for s in sessions]
            req_means.append(statistics.mean(reqs) if reqs else 0)
            lats = [
                statistics.mean([r.get("latency_ms", 0) for r in s.get("requests", [])]) or 0
                for s in sessions if s.get("requests")
            ]
            lat_means.append(statistics.mean(lats) if lats else 0)

        offsets = [xi + i * width - 0.4 + width / 2 for xi in x]
        axes[0].bar(offsets, req_means, width=width, label=region, color=colors[i])
        axes[1].bar(offsets, lat_means, width=width, label=region, color=colors[i])

    short_labels = [t.replace("-1", "").replace("-", "\n") for t in tasks]
    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels(short_labels, fontsize=8)
        ax.grid(axis="y", alpha=0.25)
        ax.legend(fontsize=7)

    axes[0].set_ylabel("Requests / session")
    axes[0].set_title("Request volume by region")
    axes[1].set_ylabel("Mean latency (ms)")
    axes[1].set_title("Request latency by region")

    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def plot_driver_comparison(trace_sessions: list[dict], output_path: Path) -> None:
    """Plot scripted-random vs LLM-driven vs human sessions."""
    PAPER_FIGURES.mkdir(parents=True, exist_ok=True)

    by_driver: dict[str, list[dict]] = defaultdict(list)
    for session in trace_sessions:
        meta = session.get("metadata", {})
        driver = meta.get("live_driver") or meta.get("source", "unknown")
        agent_type = session.get("agent_type", "unknown")
        if agent_type == "human":
            driver = "human"
        by_driver[driver].append(session)

    drivers = sorted(by_driver.keys())
    if len(drivers) < 2:
        return

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5))
    colors = {"scripted-random": "#355C7D", "agent": "#C06C84", "human": "#F8B500", "scripted": "#6C5B7B"}

    for driver in drivers:
        sessions = by_driver[driver]
        reqs = [len(s.get("requests", [])) for s in sessions]
        unique_ratios = []
        bytes_vals = []
        for s in sessions:
            n_req = len(s.get("requests", []))
            n_unique = len({r.get("url", "") for r in s.get("requests", [])})
            unique_ratios.append(n_unique / n_req if n_req > 0 else 0)
            bytes_vals.append(sum(r.get("response_size_bytes", 0) for r in s.get("requests", [])) / (1024 * 1024))

        c = colors.get(driver, "#999999")
        axes[0].hist(reqs, bins=20, alpha=0.6, label=driver, color=c)
        axes[1].hist(unique_ratios, bins=20, alpha=0.6, label=driver, color=c)
        axes[2].hist(bytes_vals, bins=20, alpha=0.6, label=driver, color=c)

    axes[0].set_xlabel("Requests / session")
    axes[0].set_title("Request volume")
    axes[1].set_xlabel("Unique-URL ratio")
    axes[1].set_title("URL reuse")
    axes[2].set_xlabel("Transferred MiB / session")
    axes[2].set_title("Data volume")

    for ax in axes:
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.25)

    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def regenerate(release: str) -> None:
    release_dir = ASL_RELEASES / release
    if not release_dir.exists():
        raise FileNotFoundError(f"Release directory not found: {release_dir}")

    summaries = load_task_summaries(release_dir)
    trace_sessions = load_trace_sessions(release_dir)
    manifest = load_or_build_manifest(release, release_dir, summaries)
    task_stats = task_stats_from_summaries(summaries)
    ctype_bytes, total_trace_bytes = content_type_stats(trace_sessions)

    plot_live_baseline(task_stats, PAPER_FIGURES / "live_baseline_by_task.pdf")
    plot_content_type_mix(ctype_bytes, total_trace_bytes, PAPER_FIGURES / "live_content_type_mix.pdf")
    plot_geo_comparison(trace_sessions, PAPER_FIGURES / "geo_comparison.pdf")
    plot_driver_comparison(trace_sessions, PAPER_FIGURES / "driver_comparison.pdf")

    combined_trace = CACHE_SIM_DIR / "traces" / f"{release}.csv"
    replay_output = CACHE_SIM_DIR / "results" / release
    combine_cache_traces(release_dir, combined_trace)

    run(
        [
            sys.executable,
            "run_sim.py",
            "--trace",
            str(combined_trace.relative_to(CACHE_SIM_DIR)),
            "--sizes",
            "1MB,5MB,10MB,25MB",
            "--output",
            str(replay_output.relative_to(CACHE_SIM_DIR)),
        ],
        cwd=CACHE_SIM_DIR,
    )

    run(
        [
            sys.executable,
            "plots.py",
            "--results",
            str((replay_output / "summary.csv").relative_to(CACHE_SIM_DIR)),
            "--output",
            str((replay_output / "figures").relative_to(CACHE_SIM_DIR)),
        ],
        cwd=CACHE_SIM_DIR,
    )

    copy_figure(replay_output / "figures" / "hit_rate_vs_size.pdf", "cache_hit_rate_vs_size.pdf")
    copy_figure(replay_output / "figures" / "policy_ranking_heatmap.pdf", "cache_policy_ranking_heatmap.pdf")

    top_content_types = [
        {
            "content_type": ctype,
            "bytes": bytes_,
            "share_pct": round(bytes_ / total_trace_bytes * 100, 3) if total_trace_bytes else 0.0,
        }
        for ctype, bytes_ in sorted(ctype_bytes.items(), key=lambda kv: kv[1], reverse=True)[:10]
    ]

    # Collect region and driver metadata from trace sessions
    regions = sorted({
        s.get("metadata", {}).get("collection_region", "unknown")
        for s in trace_sessions
        if s.get("metadata", {}).get("collection_region")
    })
    drivers = sorted({
        s.get("metadata", {}).get("live_driver") or s.get("metadata", {}).get("source", "unknown")
        for s in trace_sessions
    })

    snapshot = {
        "release": manifest["release"],
        "collected_on": manifest.get("collected_on", "unknown"),
        "collection_method": manifest.get("collection_method", "unknown"),
        "tasks": manifest["tasks"],
        "total_sessions": manifest["total_sessions"],
        "total_requests": manifest["total_requests"],
        "total_bytes": manifest["total_bytes"],
        "regions": regions if regions else ["local"],
        "drivers": drivers,
        "task_stats": task_stats,
        "top_content_types": top_content_types,
        "replay_summary": str((replay_output / "summary.csv").relative_to(ROOT)),
    }
    with (PAPER_DIR / "artifact_snapshot.json").open("w") as f:
        json.dump(snapshot, f, indent=2)
        f.write("\n")

    run(["latexmk", "-pdf", "-interaction=nonstopmode", "benchmark-paper.tex"], cwd=PAPER_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild paper artifacts from a benchmark release")
    parser.add_argument("--release", default="release-v3", help="Release name under data/")
    args = parser.parse_args()
    regenerate(args.release)


if __name__ == "__main__":
    main()
