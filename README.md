# AgentWebBench

[![Paper](https://img.shields.io/badge/Paper-IMC%202026-blue)](https://arxiv.org/abs/TODO)
[![Dataset](https://img.shields.io/badge/Dataset-HuggingFace-yellow)](https://huggingface.co/datasets/landigf/AgentWebBench)
[![License: Apache 2.0](https://img.shields.io/badge/Code-Apache%202.0-green)](LICENSE)
[![License: CC BY 4.0](https://img.shields.io/badge/Data-CC%20BY%204.0-orange)](LICENSE-DATA)

**A reproducible benchmark for browser-mediated AI agent web workloads.**

AgentWebBench provides the first public, HTTP request-level benchmark of browser-mediated AI agent traffic. Unlike agent benchmarks that measure *what* agents accomplish, AgentWebBench captures *how* they interact with web infrastructure --- enabling cache, CDN, and admission policy research on realistic agentic workloads.

## Key Findings

| Metric | Value |
|--------|-------|
| Sessions | 100 (10 task families x 10 repeats) |
| Total requests | 14,570 |
| Total bytes | 338.5 MiB |
| Unique objects | 2,522 |
| Working set | 41.1 MiB |
| Rendering overhead | 66.5% of bytes are scripts + styles |
| HTML content share | Only 3.0% of bytes |

### Cache Policy Crossover

A key finding: the optimal cache policy depends on provisioned cache size.

| Policy | HR @ 1 MiB | HR @ 10 MiB | Best at |
|--------|-----------|------------|---------|
| **GDSF** | **58.5%** | 85.2% | Small caches |
| S3-FIFO | 28.1% | 79.3% | --- |
| ARC | 26.7% | 62.7% | --- |
| W-TinyLFU | 27.0% | 64.9% | --- |
| **LRU** | 23.4% | **89.1%** | Large caches |
| LFU | 21.6% | 51.1% | --- |

No single policy is optimal. GDSF (size-aware) dominates at small caches; LRU (recency) surges ahead at 10 MiB.

## Quick Start

```python
# Load traces
import json
from pathlib import Path

release = Path("data/browseruse-live-v2")
for task_dir in sorted(release.glob("scraping/*")):
    with (task_dir / "summary.json").open() as f:
        summary = json.load(f)
    print(f"{summary['task_id']:30s} {summary['avg_requests_per_run']:6.0f} req/run")
```

### Reproduce paper figures

```bash
git clone https://github.com/landigf/AgentWebBench.git
cd AgentWebBench
pip install -r requirements.txt
python analysis/build_artifacts.py --release browseruse-live-v2
```

## Dataset

### browseruse-live-v2

| Task Family | Req/run | MiB/run | Unique-URL |
|-------------|---------|---------|------------|
| News aggregation | 364.5 +/- 10.1 | 9.44 | 92.6% |
| Product comparison | 255.0 +/- 2.9 | 7.88 | 88.4% |
| Travel planning | 245.7 +/- 17.2 | 6.56 | 86.3% |
| Job market | 196.3 +/- 27.1 | 3.54 | 90.4% |
| Documentation lookup | 124.0 +/- 1.3 | 0.80 | 99.2% |
| API comparison | 111.6 +/- 5.7 | 1.65 | 98.5% |
| Fact checking | 80.9 +/- 0.2 | 2.50 | 91.5% |
| Regulatory lookup | 39.0 +/- 0.0 | 1.05 | 100% |
| Literature review | 24.0 +/- 0.6 | 0.35 | 100% |
| Real estate | 16.0 +/- 0.0 | 0.08 | 87.5% |

### Trace Schema

Each request record contains:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp_us` | int | Request start (microseconds since epoch) |
| `url` | string | Full request URL |
| `method` | string | HTTP method (GET, POST, ...) |
| `status` | int | HTTP response status code |
| `response_size_bytes` | int | Response body size |
| `content_type` | string | Response Content-Type |
| `latency_ms` | float | Time-to-first-byte (ms) |
| `session_id` | string | Session identifier |
| `task_id` | string | Task family identifier |
| `agent_type` | string | Agent type (crawler, rag, multi-step, human) |
| `cache_key` | string | Cache-simulator-ready key |

### Output Artifacts (per task)

- `traces.json` --- full-fidelity request/response records
- `cache_trace.csv` --- cache simulator input (timestamp, key, size)
- `access_log.jsonl` --- log-format export
- `summary.json` --- per-task metadata and statistics

## Extending the Benchmark

### Add a new task

Edit `collection/tasks.yaml` and run:

```bash
python collection/runner.py --task your-new-task --surface live --live-driver scripted-random --repeats 10
```

### Add LLM-driven traces

```bash
GOOGLE_API_KEY=... python collection/runner.py --task all --surface live --live-driver agent --repeats 5
```

### Add human baseline

```bash
npx playwright codegen --save-har=human_task.har "https://target-site.com"
python collection/har_to_trace.py --input human_task.har --output data/human-baseline/
```

## Project Structure

```
AgentWebBench/
+-- data/                    # Trace data (sample + full releases)
|   +-- browseruse-live-v2/  # Current release
|   +-- sample/              # Small sample for exploration
+-- collection/              # Data collection infrastructure
|   +-- runner.py            # BrowserUse trace collector
|   +-- tasks.yaml           # Task family definitions
|   +-- Dockerfile           # Reproducible collection
+-- analysis/                # Paper figure generation + cache sim
|   +-- build_artifacts.py   # Reproduce all paper figures
|   +-- cache_sim/           # Cache policy simulator
+-- schema/                  # Trace schema definition
+-- paper/                   # LaTeX source (anonymous for review)
+-- examples/                # Quick-start notebooks
```

## Citation

If you use AgentWebBench in your research, please cite:

```bibtex
@inproceedings{agentwebbench2026,
  title     = {{AgentWebBench}: A Reproducible Benchmark for Browser-Mediated Web Workloads},
  author    = {Anonymous},
  booktitle = {Proceedings of the ACM Internet Measurement Conference (IMC)},
  year      = {2026},
  note      = {Under review}
}
```

## License

- **Code**: [Apache License 2.0](LICENSE)
- **Data**: [Creative Commons Attribution 4.0](LICENSE-DATA)
