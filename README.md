# BrowseTrace

[![License: Apache 2.0](https://img.shields.io/badge/Code-Apache%202.0-green)](LICENSE)
[![License: CC BY 4.0](https://img.shields.io/badge/Data-CC%20BY%204.0-orange)](LICENSE-DATA)
[![Paper](https://img.shields.io/badge/Paper-IMC%202026-blue)](paper/BrowseTrace.pdf)

**A reproducible benchmark for browser-mediated AI agent web workloads.**

BrowseTrace is the first public HTTP-request-level benchmark of browser-mediated AI-agent traffic. Unlike agent benchmarks that measure *what* agents accomplish, BrowseTrace captures *how* they interact with web infrastructure, enabling cache, CDN, and admission policy research on realistic agentic workloads.

> **Paper:** Landi, G.F. (2026). *BrowseTrace: Request-Level Traffic Characterization of Browser-Mediated AI Agents.* ACM Internet Measurement Conference (IMC 2026), Karlsruhe, Germany.

## Headline results

| Metric | Value |
|---|---|
| Total sessions | **1,301** |
| Scripted-random sessions | 400 (across 4 regions) |
| LLM-driven sessions | 901 (across 6 models, 5 providers) |
| Scripted cache-replay requests | 82,455 |
| LLM cache-replay requests | 357,782 |
| LLM request amplification vs scripted | **2–5×** (per-task 1–26×) |
| Rendering overhead | **69% of bytes** are scripts + stylesheets; 2.9% is HTML |

### Cache-policy findings at 5 MiB (libCacheSim, reference implementation)

| Trace | LRU | GDSF | GDSF advantage |
|---|---|---|---|
| Scripted | 37.4% | **59.5%** | +22 pp |
| LLM-driven | 43.5% | **76.2%** | +33 pp (amplified on agent traffic) |

Full Table 5 (all 6 policies × 5 cache sizes) reproduces from `data/traces/full_400_sessions.csv` and `data/traces/llm_full_901.csv` under libCacheSim in seconds.

## Six LLMs, five providers

| Provider | Model | Sessions |
|---|---|---|
| OpenAI | GPT-4.1-mini | 350 |
| Google | Gemini 2.5 Flash | 150 |
| Google | Gemini 2.5 Pro | 150 |
| Anthropic | Claude Haiku 4.5 | 100 |
| DeepSeek | DeepSeek-V3.2 (agent-trained) | 90 |
| Alibaba | Qwen 2.5-Coder 7B (open-weight) | 61 |

## Four regions (multi-region cache replay)

| Region | Vantage point |
|---|---|
| Zurich (workstation) | BrowserUse on macOS |
| US Central | Google Cloud, `us-central1` (Iowa) |
| Europe West | Google Cloud, `europe-west1` (Belgium) |
| Asia Southeast | Google Cloud, `asia-southeast1` (Singapore) |

## Quick start

```bash
curl -L -o BrowseTrace.zip https://anonymous.4open.science/api/repo/BrowseTrace/zip
unzip BrowseTrace.zip -d BrowseTrace
cd BrowseTrace
pip install -r requirements.txt

# Reproduce headline cache-policy numbers in <60 seconds
python -c "
from libcachesim import TraceReader, ReaderInitParam, TraceType, LRU, GDSF
p = ReaderInitParam(has_header=True, has_header_set=True, delimiter=',',
                    obj_id_is_num=False, obj_id_is_num_set=True)
p.time_field, p.obj_id_field, p.obj_size_field = 1, 2, 3
for label, path in [
    ('scripted', 'data/traces/full_400_sessions.csv'),
    ('llm',      'data/traces/llm_full_901.csv'),
]:
    for cls, name in [(LRU, 'LRU'), (GDSF, 'GDSF')]:
        r = TraceReader(path, trace_type=TraceType.CSV_TRACE, reader_init_params=p)
        mr, _ = cls(5*1024*1024).process_trace(r)
        print(f'{label:9s} {name:5s} @5MiB: {(1-mr)*100:.1f}%')
"
# Expected:
#   scripted LRU  @5MiB: 37.4%
#   scripted GDSF @5MiB: 59.5%
#   llm      LRU  @5MiB: 43.5%
#   llm      GDSF @5MiB: 76.2%
```

## Release manifest: `release-v3`

The `release-v3` manifest pins four components:

1. **Scripted subtree** (`data/release-v3/`) — Zurich scripted-random collection with per-task `traces.json`, `access_log.jsonl`, `cache_trace.csv`, `summary.json`.
2. **Multi-region scripted extension** (`data/release-v3-geo/`) — scripted-random sessions from `us-central1`, `europe-west1`, `asia-southeast1`.
3. **LLM-driven bundles** — per-model, per-region session directories spanning all six LLMs. See [`DATASET_CARD.md`](DATASET_CARD.md) for full layout.
4. **Canonical stitched cache-replay CSVs** (`data/traces/`) — the inputs every paper-level cache claim is replayed from:
   - `full_400_sessions.csv` (82,455 rows, scripted)
   - `llm_full_901.csv` (357,782 rows, LLM across 6 models × 4 regions)

The paper compiles every cache-policy number from those two CSVs under libCacheSim. A self-check (`verify_submission_gate.py`) confirms this on every build.

## Trace schema

Each `traces.json` record (full-fidelity) contains 32 fields organized into four groups: request context (timestamp, URL, method, initiator, resource type, session/task IDs), response metadata (status, content-type, encoded size, protocol, connection reuse), HTTP headers (with `Authorization`/`Cookie`/`Set-Cookie`/`Proxy-Authorization` stripped per the sanitization policy), and timing (DNS, TLS, TCP, TTFB, transfer in ms).

Cache-replay CSV (`cache_trace.csv`) is the simulator-ready projection: `timestamp_us, cache_key, object_size_bytes, session_id, agent_type`.

See [`schema/trace_schema.py`](schema/trace_schema.py) for the canonical schema.

## Sanitization policy

All released data has been scrubbed before publication:

- **Headers stripped** from every request/response: `Authorization`, `Cookie`, `Set-Cookie`, `Proxy-Authorization`.
- **URL query values redacted** to `_REDACTED_` in `traces.json` and `access_log.jsonl`; parameter *names* are preserved for analytical fidelity.
- **User-Agent strings** containing project-brand tokens are replaced with `BrowseTrace/1.0 (benchmark)`.
- **Cache-replay CSVs** preserve full URL uniqueness (required for correct cache keying) but are brand-scrubbed.

Tool: [`tools/sanitize_release.py`](tools/sanitize_release.py). Idempotent; safe to re-run.

## Reproducibility

See [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) for the step-by-step guide from a fresh clone:

- OS requirements, Python version, pip dependencies
- How to reproduce every figure and table in the paper
- How to re-run the submission gate (`verify_submission_gate.py`)
- How to extend the benchmark with new tasks or models

## Extending

Add a new task family or a new LLM:

```bash
# Scripted-random baseline for a new task
python collection/runner.py --task my-new-task --surface live \
                            --live-driver scripted-random --repeats 10

# LLM-driven with a specific model
GEMINI_API_KEY=... python collection/runner.py \
    --task all --surface live --live-driver agent --repeats 5 \
    --llm-model gemini-2.5-flash
```

See [`collection/tasks.yaml`](collection/tasks.yaml) for task definitions and [`collection/runner.py`](collection/runner.py) for the collector.

## Citation

If you use BrowseTrace in your research:

```bibtex
@inproceedings{browsetrace2026,
  title     = {{BrowseTrace}: Request-Level Traffic Characterization of Browser-Mediated AI Agents},
  author    = {Landi, Gennaro Francesco},
  year      = {2026},
  booktitle = {Proceedings of the ACM Internet Measurement Conference (IMC)},
  location  = {Karlsruhe, Germany},
  url       = {https://github.com/landigf/BrowseTrace},
}
```

Plain citation: see [`CITATION.cff`](CITATION.cff).

## License

- **Code**: [Apache License 2.0](LICENSE)
- **Data**: [Creative Commons Attribution 4.0](LICENSE-DATA)

## Project layout

```
BrowseTrace/
├── README.md                       — this file
├── CITATION.cff                    — academic citation metadata
├── DATASET_CARD.md                 — dataset provenance, ethics, scope
├── REPRODUCIBILITY.md              — fresh-clone reproduction guide
├── CHANGELOG.md                    — release history
├── LICENSE / LICENSE-DATA          — Apache-2.0 (code) / CC-BY-4.0 (data)
├── requirements.txt                — pinned Python dependencies
├── data/
│   ├── release-v3/                 — Zurich scripted subtree
│   ├── release-v3-geo/             — multi-region scripted
│   └── traces/                     — canonical stitched CSVs
│       ├── full_400_sessions.csv
│       └── llm_full_901.csv
├── tools/
│   └── sanitize_release.py         — scrubber (idempotent)
├── schema/
│   └── trace_schema.py             — canonical trace schema
├── collection/                     — BrowserUse runner, tasks.yaml, Dockerfile
├── analysis/                       — cache simulator + per-section scripts
├── paper/                          — LaTeX source, figures, PDF
└── verify_submission_gate.py       — submission / release gate
```
