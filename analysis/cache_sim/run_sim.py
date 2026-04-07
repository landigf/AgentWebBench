"""Run cache simulation across all policies and cache sizes.

Usage:
    python run_sim.py --trace traces/mixed_100k.csv --output results/ \
                      --sizes 1MB,10MB,50MB,100MB,500MB
"""

import argparse
import csv
import time
from pathlib import Path

from simulator import LRU, LFU, ARC, S3FIFO, WTinyLFU, GDSF

POLICIES = {
    "lru": LRU,
    "lfu": LFU,
    "arc": ARC,
    "s3fifo": S3FIFO,
    "wtinylfu": WTinyLFU,
    "gdsf": GDSF,
}


def parse_size(s: str) -> int:
    """Parse human-readable size string to bytes. E.g., '1MB' -> 1048576."""
    s = s.strip().upper()
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
    }
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if s.endswith(suffix):
            num = s[: -len(suffix)].strip()
            return int(float(num) * mult)
    return int(s)


def load_trace(path: str) -> list[tuple[str, int, str]]:
    """Load CSV trace file.

    Returns list of (cache_key, object_size_bytes, agent_type).
    """
    trace = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trace.append((
                row["cache_key"],
                int(row["object_size_bytes"]),
                row["agent_type"],
            ))
    return trace


def run_all(
    trace: list[tuple[str, int, str]],
    sizes: list[int],
    output_dir: Path,
) -> None:
    """Run all policies x all sizes, save results CSV + print summary."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    total_configs = len(POLICIES) * len(sizes)
    config_num = 0

    for size_bytes in sizes:
        size_label = format_size(size_bytes)
        for policy_name, policy_cls in POLICIES.items():
            config_num += 1
            print(f"  [{config_num}/{total_configs}] {policy_name} @ {size_label}...", end=" ", flush=True)

            cache = policy_cls(size_bytes)
            t0 = time.time()
            for key, obj_size, _ in trace:
                cache.access(key, obj_size)
            duration = time.time() - t0

            results.append({
                "policy": policy_name,
                "cache_size_bytes": size_bytes,
                "cache_size_label": size_label,
                "hit_rate": cache.stats.hit_rate,
                "byte_hit_rate": cache.stats.byte_hit_rate,
                "hits": cache.stats.hits,
                "misses": cache.stats.misses,
                "evictions": cache.stats.evictions,
                "duration_sec": round(duration, 3),
            })
            print(
                f"HR={cache.stats.hit_rate:.3f} BHR={cache.stats.byte_hit_rate:.3f} "
                f"({duration:.1f}s)"
            )

    # Save summary CSV
    summary_path = output_dir / "summary.csv"
    with open(summary_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    print(f"\nResults saved to {summary_path}")

    # Also save per-agent-type results
    agent_types = sorted(set(row[2] for row in trace))
    if len(agent_types) > 1:
        print("\nRunning per-agent-type analysis...")
        # Split trace by agent type
        traces_by_type: dict[str, list[tuple[str, int, str]]] = {}
        for key, obj_size, atype in trace:
            traces_by_type.setdefault(atype, []).append((key, obj_size, atype))

        per_type_results = []
        for atype, atrace in sorted(traces_by_type.items()):
            for size_bytes in sizes:
                size_label = format_size(size_bytes)
                for policy_name, policy_cls in POLICIES.items():
                    cache = policy_cls(size_bytes)
                    for key, obj_size, _ in atrace:
                        cache.access(key, obj_size)
                    per_type_results.append({
                        "agent_type": atype,
                        "policy": policy_name,
                        "cache_size_bytes": size_bytes,
                        "cache_size_label": size_label,
                        "hit_rate": cache.stats.hit_rate,
                        "byte_hit_rate": cache.stats.byte_hit_rate,
                        "n_requests": len(atrace),
                    })

        per_type_path = output_dir / "per_agent_type.csv"
        with open(per_type_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(per_type_results[0].keys()))
            writer.writeheader()
            writer.writerows(per_type_results)
        print(f"Per-agent-type results saved to {per_type_path}")


def format_size(n: int) -> str:
    """Format bytes as human-readable string."""
    if n >= 1024**3:
        return f"{n / 1024**3:.0f}GB"
    elif n >= 1024**2:
        return f"{n / 1024**2:.0f}MB"
    elif n >= 1024:
        return f"{n / 1024:.0f}KB"
    return f"{n}B"


def main():
    parser = argparse.ArgumentParser(description="Run cache simulation.")
    parser.add_argument("--trace", type=str, required=True, help="Path to trace CSV")
    parser.add_argument("--output", type=str, default="results/", help="Output directory")
    parser.add_argument(
        "--sizes",
        type=str,
        default="1MB,10MB,50MB,100MB,500MB",
        help="Comma-separated cache sizes (e.g., 1MB,10MB,50MB)",
    )
    parser.add_argument(
        "--policies",
        type=str,
        default=None,
        help="Comma-separated policy names (default: all)",
    )
    args = parser.parse_args()

    sizes = [parse_size(s) for s in args.sizes.split(",")]
    output_dir = Path(args.output)

    print(f"Loading trace from {args.trace}...")
    trace = load_trace(args.trace)
    print(f"  {len(trace):,} requests loaded")

    # Count unique objects and total bytes
    unique_keys = set()
    total_bytes = 0
    for key, obj_size, _ in trace:
        unique_keys.add(key)
        total_bytes += obj_size
    print(f"  {len(unique_keys):,} unique objects, {total_bytes / 1024**2:.1f} MB total")
    print(f"  Cache sizes: {', '.join(format_size(s) for s in sizes)}")
    print()

    run_all(trace, sizes, output_dir)


if __name__ == "__main__":
    main()
