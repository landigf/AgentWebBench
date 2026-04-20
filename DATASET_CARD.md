# Dataset Card: BrowseTrace

*(Following the [HuggingFace Datasets Card template](https://huggingface.co/docs/hub/datasets-cards) adapted for web-measurement artifacts.)*

## Overview

- **Dataset:** BrowseTrace
- **Version:** v3 (release manifest `browseruse-live-v3`, released 2026-04-29)
- **Curator:** Gennaro Francesco Landi (ETH Zurich)
- **License (data):** [CC BY 4.0](LICENSE-DATA)
- **License (code):** [Apache 2.0](LICENSE)
- **Primary reference:** Landi (2026). *BrowseTrace: Request-Level Traffic Characterization of Browser-Mediated AI Agents.* In Proceedings of IMC 2026.
- **Canonical location:** https://github.com/landigf/BrowseTrace
- **Supported tasks:** cache-policy evaluation, CDN workload characterization, web-measurement longitudinal study, agent traffic modelling.

## Scope

1,301 browser-mediated agent sessions across 10 task families. Two execution modes:

| Mode | Sessions | Regions | Use |
|---|---|---|---|
| Scripted-random | 400 | 4 (Zurich + 3 GCP) | Reproducible stress-test baseline, credential-free |
| LLM-driven | 901 | 4 (same 4 regions) | Real browser-mediated AI-agent traffic |

Six LLMs across five providers:

| Provider | Model | Sessions | Capability tier |
|---|---|---|---|
| OpenAI | GPT-4.1-mini | 350 | Frontier closed-source (cost-optimized) |
| Google | Gemini 2.5 Flash | 150 | Frontier closed-source (cost-optimized) |
| Google | Gemini 2.5 Pro | 150 | Frontier closed-source (high-capability) |
| Anthropic | Claude Haiku 4.5 | 100 | Frontier closed-source (fast/cheap) |
| DeepSeek | DeepSeek-V3.2 | 90 | Agent-post-trained (reasoning-first) |
| Alibaba | Qwen 2.5-Coder 7B | 61 | Open-weight, edge-runnable |

## Task families

10 task families designed to span navigation regimes: breadth-first, depth-first, multi-site comparison, structured lookup.

1. API comparison (weather API providers)
2. Documentation lookup (Python, MDN)
3. Fact checking (EU regulatory sources)
4. Job market (Indeed, Jobs.ch, Glassdoor)
5. Literature review (arXiv, Google Scholar)
6. News aggregation (tech news sites)
7. Product comparison (cloud GPU providers)
8. Real estate (apartment listings)
9. Regulatory lookup (GDPR reference)
10. Travel planning (flights, hotels)

See [`collection/tasks.yaml`](collection/tasks.yaml) for full target site lists and parameters.

## File formats

### Per-task artifacts (`data/browseruse-live-v3/scraping/<task>/`)

| File | Format | Purpose |
|---|---|---|
| `traces.json` | JSON (full-fidelity) | 32 fields per request: context, metadata, headers, timing |
| `cache_trace.csv` | CSV | Simulator-ready: timestamp, cache_key, object_size, session_id, agent_type |
| `access_log.jsonl` | JSONL | Log-format export for streaming analysis |
| `summary.json` | JSON | Per-task aggregate statistics + provenance |

### Canonical stitched cache-replay CSVs (`data/traces/`)

| File | Rows | Scope |
|---|---|---|
| `full_400_sessions.csv` | 82,455 | All scripted sessions across 4 regions (cacheable filter: GET, status 200, non-zero body) |
| `llm_full_901.csv` | 357,782 | All LLM sessions across 6 models × 4 regions (same cacheable filter) |

Both are built from the per-task `cache_trace.csv` files via `paper/regenerate_full_snapshot.py`.

## Provenance

- **Collection substrate:** BrowserUse v0.2 driving Chromium via Chrome DevTools Protocol (CDP). Playwright in Docker for GCP regions; native macOS for Zurich workstation.
- **Collection period:** 2026-02 through 2026-04.
- **PRNG seed:** `BENCH_SEED=42` (fixed for scripted-random).
- **Target policy:** Only publicly accessible pages. No authentication, no form submission, no payment, no login flows. Robots.txt respected per domain.

## Sanitization (applied to every released file)

Sanitization tool: [`tools/sanitize_release.py`](tools/sanitize_release.py). Idempotent. Run before every release.

| Scrub | Where |
|---|---|
| Strip `Authorization`, `Cookie`, `Set-Cookie`, `Proxy-Authorization` headers | `traces.json`, `access_log.jsonl` (response_headers + request_headers) |
| Redact URL query parameter values to `_REDACTED_` (names preserved) | `traces.json`, `access_log.jsonl` |
| Replace project-brand User-Agent strings with `BrowseTrace/1.0 (benchmark)` | all files |
| Brand-string scrub (recursive) for any residual mentions | all files |
| Preserve URL uniqueness in cache-replay CSVs (brand scrub only, no query redaction) | `cache_trace.csv`, `full_400_sessions.csv`, `llm_full_901.csv` |

## Ethics

All sessions target publicly accessible web pages. No authentication or form submission. Rate-limited (< 2,000 requests per task per region). `robots.txt` reviewed per target; disallowed paths avoided or minimally sampled.

**Human subjects:** A single qualitative self-study session was collected by one researcher across all 10 tasks (N=1), used purely as a directional reference point in the appendix. Under local institutional policy, self-study sessions with no external participants fall outside human-subjects review requirements.

**PII:** The release contains request-level metadata and response sizes only. No response bodies. No personally identifiable information. Cookies and Authorization headers are stripped.

## Known limitations

- **Scripted-random is a stress-test driver**, not a proxy for human behavior. It is a reproducible, credential-free baseline against which agent traffic can be contrasted.
- **Substrate heterogeneity:** Zurich uses BrowserUse on macOS; cloud uses Playwright on Linux in Docker. The paper's geographic analysis restricts cross-region claims to the three cloud regions (substrate held constant).
- **10 task families** is intentionally narrow for manageable execution time. Future releases will broaden coverage.
- **HTTP/2 multiplexing and HTTP/3 effects** are recorded but not yet analyzed.
- **Bot detection:** Fewer than 1% of sessions encountered anti-bot blocking; flagged in per-session `navigation_status`.
- **Single collection period** (Feb–Apr 2026); longitudinal repeated collection is planned future work.

## Reference implementation

All cache-policy numbers in the paper are derived under [libCacheSim](https://github.com/1a1a11a/libCacheSim) v0.3.3+, a widely-used C reference cache simulator with Python bindings. Cross-project reproducibility: see `verify_submission_gate.py`, which runs libCacheSim on the canonical CSVs and checks against paper-reported numbers.

Policies evaluated: LRU, LFU, ARC, S3-FIFO, W-TinyLFU, GDSF (Greedy-Dual-Size-Frequency). Cache sizes: 1, 5, 10, 25, 50 MiB.

## How to cite

If you use BrowseTrace in your research, please cite the IMC 2026 paper:

```bibtex
@inproceedings{browsetrace2026,
  title     = {{BrowseTrace}: Request-Level Traffic Characterization of Browser-Mediated AI Agents},
  author    = {Landi, Gennaro Francesco},
  year      = {2026},
  booktitle = {Proceedings of the ACM Internet Measurement Conference (IMC)},
  location  = {Karlsruhe, Germany},
}
```

## Contact

Open an issue: https://github.com/landigf/BrowseTrace/issues
Email: `landig@ethz.ch`
