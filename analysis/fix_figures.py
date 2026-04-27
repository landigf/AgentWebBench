#!/usr/bin/env python3
"""Regenerate buggy paper figures with layout fixes.

Fixes:
  Figure 4 (per_task_content_types.pdf) - legend moved outside plot
  Figure 5 (inter_request_timing_cdf.pdf) - legend moved OUTSIDE plot area
  Figure 7 (geo_request_volume.pdf) - legend/tick text made readable
  Figure 8 (geo_latency.pdf) - tick/axis/legend fontsizes bumped up

Usage:
  python3 fix_figures.py
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42  # TrueType (no Type 3) for IMC compliance
matplotlib.rcParams["ps.fonttype"] = 42
matplotlib.rcParams["font.size"] = 9      # IMC: figure fonts >= 9pt
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
RELEASE_DIR = ROOT / "asl-project" / "data" / "releases" / "release-v3" / "scraping"
MULTIREGION_DIR = ROOT / "asl-project" / "data" / "round9" / "round9-multiregion-20260415"
FIGURES_DIR = Path(__file__).resolve().parents[1] / "figures"

# ColorBrewer Set2 palette
SET2 = plt.cm.Set2.colors


def load_trace_sessions(release_dir: Path) -> list[dict]:
    """Load all trace sessions from a release directory."""
    sessions = []
    for traces_file in sorted(release_dir.glob("*/traces.json")):
        with traces_file.open() as f:
            data = json.load(f)
        if isinstance(data, dict) and "sessions" in data:
            sessions.extend(data["sessions"])
        elif isinstance(data, list):
            sessions.extend(data)
    return sessions


def load_multiregion_sessions(base_dir: Path) -> list[dict]:
    """Load all trace sessions from multi-region round9 data."""
    sessions = []
    for traces_file in sorted(base_dir.rglob("traces.json")):
        with traces_file.open() as f:
            data = json.load(f)
        if isinstance(data, dict) and "sessions" in data:
            sessions.extend(data["sessions"])
        elif isinstance(data, list):
            sessions.extend(data)
    return sessions


# ── Figure 4: per_task_content_types.pdf ──────────────────────────────────

def fix_per_task_content_types():
    """Stacked bar chart of byte share (%) by content type for each task.
    Fix: move legend outside the plot to avoid overlapping last task columns.
    """
    print("Generating Figure 4: per_task_content_types.pdf ...")
    sessions = load_trace_sessions(RELEASE_DIR)

    # Group bytes by (task_id, content_type)
    by_task_ctype: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    task_totals: dict[str, int] = defaultdict(int)

    for s in sessions:
        task_id = s.get("task_id", "unknown")
        for r in s.get("requests", []):
            ct = (r.get("content_type") or "unknown").split(";")[0].strip().lower()
            size = int(r.get("response_size_bytes", 0) or 0)
            by_task_ctype[task_id][ct] += size
            task_totals[task_id] += size

    tasks = sorted(by_task_ctype.keys())

    # Determine top content types across all tasks, group rest as "other"
    global_ctype_bytes: dict[str, int] = defaultdict(int)
    for task_id, ctypes in by_task_ctype.items():
        for ct, b in ctypes.items():
            global_ctype_bytes[ct] += b
    top_ctypes = [ct for ct, _ in sorted(global_ctype_bytes.items(), key=lambda x: x[1], reverse=True)[:8]]

    # Merge similar JS types
    js_types = {"application/javascript", "text/javascript", "application/x-javascript"}
    merged_types = []
    js_seen = False
    for ct in top_ctypes:
        if ct in js_types:
            if not js_seen:
                merged_types.append("javascript")
                js_seen = True
        else:
            merged_types.append(ct)
    # Also merge any remaining JS
    label_map = {}
    for ct in top_ctypes:
        if ct in js_types:
            label_map[ct] = "javascript"
        else:
            label_map[ct] = ct

    # Recompute with merged types
    final_types = []
    seen = set()
    for ct in top_ctypes:
        mapped = label_map[ct]
        if mapped not in seen:
            final_types.append(mapped)
            seen.add(mapped)

    # Build percentage matrix: rows = tasks, columns = content types
    pct_matrix = []
    for task_id in tasks:
        total = task_totals[task_id]
        if total == 0:
            pct_matrix.append([0.0] * (len(final_types) + 1))
            continue
        row = []
        accounted = 0.0
        for ft in final_types:
            # Sum all raw ctypes that map to this final type
            val = 0
            for raw_ct, mapped in label_map.items():
                if mapped == ft:
                    val += by_task_ctype[task_id].get(raw_ct, 0)
            pct = val / total * 100
            row.append(pct)
            accounted += pct
        # Also add non-top ctypes to "other"
        other_bytes = 0
        for ct, b in by_task_ctype[task_id].items():
            if ct not in label_map:
                other_bytes += b
        other_pct = other_bytes / total * 100 if total else 0
        row.append(100.0 - accounted)  # "other" gets the remainder
        pct_matrix.append(row)

    categories = final_types + ["other"]
    colors = list(SET2[:len(categories)])

    # Short task labels
    short_labels = [t.replace("-1", "").replace("-", "\n") for t in tasks]

    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    x = np.arange(len(tasks))
    bar_width = 0.7
    bottoms = np.zeros(len(tasks))

    for i, cat in enumerate(categories):
        vals = [pct_matrix[j][i] for j in range(len(tasks))]
        ax.bar(x, vals, bar_width, bottom=bottoms, label=cat, color=colors[i % len(colors)])
        bottoms += np.array(vals)

    ax.set_ylabel("Byte share (%)", fontsize=11)
    ax.set_xlabel("Task", fontsize=11)
    ax.set_xticks(x)
    ax.set_xticklabels(short_labels, fontsize=8, ha="center")
    ax.set_ylim(0, 105)
    ax.grid(axis="y", alpha=0.25)

    # Fix: move legend outside the plot
    ax.legend(
        bbox_to_anchor=(1.02, 1),
        loc="upper left",
        fontsize=8,
        frameon=True,
    )
    fig.subplots_adjust(right=0.75)

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES_DIR / "per_task_content_types.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  Saved per_task_content_types.pdf")


# ── Figure 5: inter_request_timing_cdf.pdf ───────────────────────────────

def fix_inter_request_timing_cdf():
    """CDF of inter-request gap (ms) by task on log-x scale.
    Fix: group tasks by depth-first (solid, warm) vs breadth-first (dashed,
    cool) to match caption narrative. Tab10 palette for high contrast;
    legend outside plot; line width 1.8 for readability.
    """
    print("Generating Figure 5: inter_request_timing_cdf.pdf ...")
    sessions = load_trace_sessions(RELEASE_DIR)

    # Compute inter-request gaps per task
    by_task: dict[str, list[float]] = defaultdict(list)
    for s in sessions:
        task_id = s.get("task_id", "unknown")
        requests = s.get("requests", [])
        timestamps = sorted(r.get("timestamp_us", 0) for r in requests)
        for i in range(1, len(timestamps)):
            gap_ms = (timestamps[i] - timestamps[i - 1]) / 1000.0  # us -> ms
            if gap_ms > 0:
                by_task[task_id].append(gap_ms)

    # Task categorization: depth-first tasks have a dominant site and produce
    # tight request bursts; breadth-first tasks traverse many sites.
    # Task IDs carry a trailing "-1"; match on prefix.
    depth_first_prefixes = (
        "api-integration",
        "documentation-lookup",
        "regulatory-lookup",
        "travel-planning",
    )
    # Everything else is treated as breadth-first: fact-checking, job-market,
    # literature-review, news-aggregation, product-comparison, real-estate.

    # Warm palette for depth-first, cool for breadth-first. Uses tab10 so
    # adjacent lines are distinguishable even in grayscale print.
    warm = ["#d62728", "#ff7f0e", "#e377c2", "#8c564b"]   # red, orange, pink, brown
    cool = ["#1f77b4", "#2ca02c", "#17becf", "#9467bd", "#7f7f7f", "#bcbd22"]

    tasks = sorted(by_task.keys())

    fig, ax = plt.subplots(figsize=(8.5, 3.8))
    warm_i = 0
    cool_i = 0

    for task_id in tasks:
        gaps = sorted(by_task[task_id])
        n = len(gaps)
        if n == 0:
            continue
        cdf_y = np.arange(1, n + 1) / n
        short_label = task_id.replace("-1", "").replace("-", " ")
        is_depth = task_id.startswith(depth_first_prefixes)
        if is_depth:
            color = warm[warm_i % len(warm)]
            linestyle = "-"
            warm_i += 1
        else:
            color = cool[cool_i % len(cool)]
            linestyle = "--"
            cool_i += 1
        ax.plot(gaps, cdf_y, label=short_label, color=color,
                linestyle=linestyle, linewidth=1.8)

    ax.set_xscale("log")
    ax.set_xlabel("Inter-request gap (ms)", fontsize=11)
    ax.set_ylabel("CDF", fontsize=11)
    ax.tick_params(axis="both", labelsize=10)
    ax.set_ylim(0, 1.02)
    ax.grid(True, alpha=0.25)

    # Legend with a category hint via title
    ax.legend(
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        prop={"size": 8.5},
        frameon=True,
        ncol=1,
        title="solid: depth-first\ndashed: breadth-first",
        title_fontsize=8,
    )

    fig.subplots_adjust(right=0.72)
    fig.savefig(FIGURES_DIR / "inter_request_timing_cdf.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  Saved inter_request_timing_cdf.pdf")


# ── Figure 7: geo_request_volume.pdf ─────────────────────────────────────

def fix_geo_request_volume():
    """Grouped bars of mean requests-per-session by region and model.
    Caption in tex: 'Mean request volume per session by region.'
    """
    print("Generating Figure 7: geo_request_volume.pdf ...")
    sessions = load_multiregion_sessions(MULTIREGION_DIR)

    # Collect per-session request counts grouped by (region, model)
    by_region_model: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for s in sessions:
        meta = s.get("metadata", {})
        region = meta.get("collection_region", "unknown")
        model = meta.get("llm_model", "unknown")
        if region == "unknown" or model == "unknown":
            continue
        n_req = len(s.get("requests", []))
        if n_req > 0:
            by_region_model[region][model].append(n_req)

    regions = sorted(by_region_model.keys())
    all_models = set()
    for rm in by_region_model.values():
        all_models.update(rm.keys())
    models = sorted(all_models)

    if not regions or not models:
        print("  WARNING: insufficient data for geo_request_volume figure")
        return

    fig, ax = plt.subplots(figsize=(10, 4.6))
    x = np.arange(len(regions))
    n_models = len(models)
    width = 0.8 / n_models
    colors = SET2

    for i, model in enumerate(models):
        means = []
        for reg in regions:
            vals = by_region_model[reg].get(model, [])
            means.append(statistics.mean(vals) if vals else 0)
        offsets = x + i * width - 0.4 + width / 2
        ax.bar(offsets, means, width=width, label=model, color=colors[i % len(colors)])

    ax.set_xticks(x)
    ax.set_xticklabels(regions, fontsize=11, ha="center")
    ax.tick_params(axis="y", labelsize=11)
    ax.set_ylabel("Mean requests per session", fontsize=12)
    ax.set_xlabel("Region", fontsize=12)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=11, frameon=True, loc="upper right")

    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "geo_request_volume.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  Saved geo_request_volume.pdf")


# ── Figure 8: geo_latency.pdf ────────────────────────────────────────────

def fix_geo_latency():
    """Grouped bar chart of median per-request latency by region and task.
    Fix: increase tick labels and axis text sizes.
    """
    print("Generating Figure 8: geo_latency.pdf ...")
    sessions = load_multiregion_sessions(MULTIREGION_DIR)

    # Group latencies by (region, task_id)
    by_region_task: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for s in sessions:
        meta = s.get("metadata", {})
        region = meta.get("collection_region", "unknown")
        if region == "unknown":
            continue
        task_id = s.get("task_id", "unknown")
        for r in s.get("requests", []):
            lat = r.get("latency_ms")
            if lat and lat > 0:
                by_region_task[region][task_id].append(lat)

    regions = sorted(by_region_task.keys())
    all_tasks = set()
    for reg_tasks in by_region_task.values():
        all_tasks.update(reg_tasks.keys())
    tasks = sorted(all_tasks)

    if len(regions) < 2 or not tasks:
        print("  WARNING: insufficient data for geo_latency figure")
        return

    fig, ax = plt.subplots(figsize=(11, 4.4))
    x = np.arange(len(tasks))
    n_regions = len(regions)
    width = 0.8 / n_regions
    colors = SET2

    for i, region in enumerate(regions):
        medians = []
        for task in tasks:
            lats = by_region_task[region].get(task, [])
            medians.append(statistics.median(lats) if lats else 0)
        offsets = x + i * width - 0.4 + width / 2
        ax.bar(offsets, medians, width=width, label=region, color=colors[i % len(colors)])

    short_labels = [t.replace("-1", "").replace("-", "\n") for t in tasks]

    # Fix: bump all fontsizes for readability
    ax.set_xticks(x)
    ax.set_xticklabels(short_labels, fontsize=10, ha="center")
    ax.tick_params(axis="y", labelsize=11)
    ax.set_ylabel("Median latency (ms)", fontsize=12)
    ax.set_xlabel("Task", fontsize=12)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=11, frameon=True, loc="upper right")

    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "geo_latency.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  Saved geo_latency.pdf")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    fix_per_task_content_types()
    fix_inter_request_timing_cdf()
    fix_geo_request_volume()
    fix_geo_latency()
    print("\nAll figures regenerated in", FIGURES_DIR)


if __name__ == "__main__":
    main()
