"""Generate paper figures from simulation results.

Usage:
    python plots.py --results results/summary.csv --output results/figures/
    python plots.py --results results/summary.csv --per-type results/per_agent_type.csv --output results/figures/
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


# Academic style
plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.grid": True,
    "grid.alpha": 0.3,
    "font.size": 11,
    "axes.labelsize": 12,
    "axes.titlesize": 13,
    "legend.fontsize": 9,
    "figure.dpi": 150,
    "savefig.dpi": 300,
})

POLICY_COLORS = {
    "lru": "#1f77b4",
    "lfu": "#ff7f0e",
    "arc": "#2ca02c",
    "s3fifo": "#d62728",
    "wtinylfu": "#9467bd",
    "gdsf": "#8c564b",
}

POLICY_MARKERS = {
    "lru": "o",
    "lfu": "s",
    "arc": "^",
    "s3fifo": "D",
    "wtinylfu": "v",
    "gdsf": "P",
}

POLICY_LABELS = {
    "lru": "LRU",
    "lfu": "LFU",
    "arc": "ARC",
    "s3fifo": "S3-FIFO",
    "wtinylfu": "W-TinyLFU",
    "gdsf": "GDSF",
}


def load_summary(path: str) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def load_per_type(path: str) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def plot_hit_rate_vs_size(data: list[dict], output_dir: Path) -> None:
    """Fig 1: Hit rate vs cache size, one line per policy."""
    fig, ax = plt.subplots(figsize=(7, 4.5))

    # Group by policy
    by_policy: dict[str, list] = defaultdict(list)
    for row in data:
        by_policy[row["policy"]].append(row)

    for policy, rows in sorted(by_policy.items()):
        rows.sort(key=lambda r: int(r["cache_size_bytes"]))
        sizes = [int(r["cache_size_bytes"]) for r in rows]
        rates = [float(r["hit_rate"]) * 100 for r in rows]
        ax.plot(
            sizes, rates,
            marker=POLICY_MARKERS.get(policy, "o"),
            color=POLICY_COLORS.get(policy, "gray"),
            label=POLICY_LABELS.get(policy, policy),
            linewidth=1.8,
            markersize=6,
        )

    ax.set_xscale("log")
    ax.set_xlabel("Cache Size (bytes)")
    ax.set_ylabel("Hit Rate (%)")
    ax.set_title("Hit Rate vs Cache Size")
    ax.legend(loc="lower right")
    ax.set_ylim(bottom=0)

    # Format x-axis with human-readable labels
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(_size_formatter))

    path = output_dir / "hit_rate_vs_size.pdf"
    fig.savefig(path)
    plt.close(fig)
    print(f"  Saved {path}")


def plot_byte_hit_rate_vs_size(data: list[dict], output_dir: Path) -> None:
    """Fig 2: Byte hit rate vs cache size."""
    fig, ax = plt.subplots(figsize=(7, 4.5))

    by_policy: dict[str, list] = defaultdict(list)
    for row in data:
        by_policy[row["policy"]].append(row)

    for policy, rows in sorted(by_policy.items()):
        rows.sort(key=lambda r: int(r["cache_size_bytes"]))
        sizes = [int(r["cache_size_bytes"]) for r in rows]
        rates = [float(r["byte_hit_rate"]) * 100 for r in rows]
        ax.plot(
            sizes, rates,
            marker=POLICY_MARKERS.get(policy, "o"),
            color=POLICY_COLORS.get(policy, "gray"),
            label=POLICY_LABELS.get(policy, policy),
            linewidth=1.8,
            markersize=6,
        )

    ax.set_xscale("log")
    ax.set_xlabel("Cache Size (bytes)")
    ax.set_ylabel("Byte Hit Rate (%)")
    ax.set_title("Byte Hit Rate vs Cache Size")
    ax.legend(loc="lower right")
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(_size_formatter))

    path = output_dir / "byte_hit_rate_vs_size.pdf"
    fig.savefig(path)
    plt.close(fig)
    print(f"  Saved {path}")


def plot_hit_rate_by_traffic_type(
    per_type_data: list[dict], output_dir: Path
) -> None:
    """Fig 3: Grouped bar chart — hit rate by agent type for each policy.

    Uses the largest cache size available.
    """
    if not per_type_data:
        print("  Skipping per-type plot (no per_agent_type.csv)")
        return

    # Use the largest cache size
    max_size = max(int(r["cache_size_bytes"]) for r in per_type_data)
    data = [r for r in per_type_data if int(r["cache_size_bytes"]) == max_size]

    # Organize: policy -> agent_type -> hit_rate
    grid: dict[str, dict[str, float]] = defaultdict(dict)
    for row in data:
        grid[row["policy"]][row["agent_type"]] = float(row["hit_rate"]) * 100

    policies = sorted(grid.keys())
    agent_types = sorted(set(row["agent_type"] for row in data))
    n_types = len(agent_types)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(policies))
    width = 0.8 / n_types

    type_colors = {
        "human": "#4c72b0",
        "crawler": "#dd8452",
        "rag": "#55a868",
        "multi_step": "#c44e52",
    }

    for i, atype in enumerate(agent_types):
        rates = [grid[p].get(atype, 0) for p in policies]
        offset = (i - n_types / 2 + 0.5) * width
        ax.bar(
            x + offset, rates, width * 0.9,
            label=atype.replace("_", " ").title(),
            color=type_colors.get(atype, "gray"),
        )

    ax.set_xticks(x)
    ax.set_xticklabels([POLICY_LABELS.get(p, p) for p in policies], rotation=15)
    ax.set_ylabel("Hit Rate (%)")
    ax.set_title(f"Hit Rate by Traffic Type (cache = {_format_size(max_size)})")
    ax.legend(loc="upper right")
    ax.set_ylim(bottom=0)

    path = output_dir / "hit_rate_by_traffic_type.pdf"
    fig.savefig(path)
    plt.close(fig)
    print(f"  Saved {path}")


def plot_ranking_heatmap(data: list[dict], output_dir: Path) -> None:
    """Fig 4: Heatmap — rows=policies, cols=cache sizes, cells=rank (1-6)."""
    # Organize: size -> policy -> hit_rate
    grid: dict[int, dict[str, float]] = defaultdict(dict)
    for row in data:
        size = int(row["cache_size_bytes"])
        grid[size][row["policy"]] = float(row["hit_rate"])

    sizes = sorted(grid.keys())
    policies = sorted(set(row["policy"] for row in data))
    n_policies = len(policies)
    n_sizes = len(sizes)

    # Compute ranks (1 = best)
    rank_matrix = np.zeros((n_policies, n_sizes), dtype=int)
    for j, size in enumerate(sizes):
        rates = [(grid[size].get(p, 0), p) for p in policies]
        rates.sort(key=lambda x: -x[0])  # descending
        for rank, (_, p) in enumerate(rates, 1):
            i = policies.index(p)
            rank_matrix[i, j] = rank

    fig, ax = plt.subplots(figsize=(8, 4))

    # Custom colormap: green (rank 1) to red (rank 6)
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("rank", ["#2ca02c", "#ffffcc", "#d62728"], N=n_policies)

    im = ax.imshow(rank_matrix, cmap=cmap, vmin=1, vmax=n_policies, aspect="auto")

    # Annotate cells
    for i in range(n_policies):
        for j in range(n_sizes):
            ax.text(j, i, str(rank_matrix[i, j]),
                    ha="center", va="center", fontsize=12, fontweight="bold",
                    color="white" if rank_matrix[i, j] in (1, n_policies) else "black")

    ax.set_xticks(range(n_sizes))
    ax.set_xticklabels([_format_size(s) for s in sizes])
    ax.set_yticks(range(n_policies))
    ax.set_yticklabels([POLICY_LABELS.get(p, p) for p in policies])
    ax.set_xlabel("Cache Size")
    ax.set_title("Policy Ranking (1 = best hit rate)")

    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("Rank")

    path = output_dir / "policy_ranking_heatmap.pdf"
    fig.savefig(path)
    plt.close(fig)
    print(f"  Saved {path}")


def _size_formatter(x, _pos):
    """Format bytes for axis ticks."""
    return _format_size(int(x))


def _format_size(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.0f} GB"
    elif n >= 1024**2:
        return f"{n / 1024**2:.0f} MB"
    elif n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def main():
    parser = argparse.ArgumentParser(description="Generate figures from simulation results.")
    parser.add_argument("--results", type=str, required=True, help="Path to summary.csv")
    parser.add_argument("--per-type", type=str, default=None, help="Path to per_agent_type.csv")
    parser.add_argument("--output", type=str, default="results/figures/", help="Output directory for figures")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading results...")
    data = load_summary(args.results)
    print(f"  {len(data)} rows loaded")

    per_type_data = []
    if args.per_type:
        per_type_data = load_per_type(args.per_type)
        print(f"  {len(per_type_data)} per-type rows loaded")
    else:
        # Try auto-detect
        per_type_path = Path(args.results).parent / "per_agent_type.csv"
        if per_type_path.exists():
            per_type_data = load_per_type(str(per_type_path))
            print(f"  {len(per_type_data)} per-type rows auto-loaded from {per_type_path}")

    print("\nGenerating figures...")
    plot_hit_rate_vs_size(data, output_dir)
    plot_byte_hit_rate_vs_size(data, output_dir)
    plot_hit_rate_by_traffic_type(per_type_data, output_dir)
    plot_ranking_heatmap(data, output_dir)
    print("\nDone.")


if __name__ == "__main__":
    main()
