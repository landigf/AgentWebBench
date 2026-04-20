# Changelog

All notable changes to BrowseTrace are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0] — 2026-04-29 (IMC 2026 Cycle 2 submission)

### Added
- Full 1,301-session corpus: 400 scripted-random + 901 LLM-driven.
- Six LLMs from five providers: GPT-4.1-mini, Gemini 2.5 Flash/Pro, Claude Haiku 4.5, DeepSeek-V3.2, Qwen 2.5-Coder 7B.
- Multi-region collection across 4 vantage points (Zurich, us-central1, europe-west1, asia-southeast1).
- Canonical stitched cache-replay CSVs at `data/traces/`:
  - `full_400_sessions.csv` (82,455 scripted requests)
  - `llm_full_901.csv` (357,782 LLM requests)
- `verify_submission_gate.py` — submission/release gate that cross-checks abstract, body, appendix tables, anonymity, and libCacheSim numbers on every compile.
- `tools/sanitize_release.py` — idempotent release-data scrubber.
- `DATASET_CARD.md`, `REPRODUCIBILITY.md`, `CHANGELOG.md` — dataset governance docs.
- Dataset-card fields: provenance, sanitization policy, known limitations, reference implementation (libCacheSim).

### Changed
- **Renamed from AgentWebBench to BrowseTrace** (paper title and repo name).
- All cache-policy numbers now reported from libCacheSim (the reference C implementation), not our purpose-built Python simulator. The internal Python simulator diverged on frequency-adaptive policies at small caches (peak 18 pp on W-TinyLFU at 1 MiB); libCacheSim is now canonical.
- Abstract headline: LRU 37.4% vs GDSF 59.5% at 5 MiB on scripted; 43.5% vs 76.2% on LLM traffic.
- Release description: `browseruse-live-v3` is now a manifest that pins the scripted subtree, the per-model LLM bundles, and the two canonical cache CSVs; this replaces the earlier ambiguous framing that implied the named directory alone held 1,301 sessions.

### Fixed
- RFC 9309 bibliography: authors corrected to Koster, Illyes, Zeller, Sassman (was incorrectly attributed to "Google").
- JavaScript content-type classification: now reports 62.1% (all JS subtypes including `application/x-javascript`) instead of 60.6% (two subtypes only); scripts+styles total now 68.8% instead of 67.3%.
- Overgeneralization claims: regional invariance scoped to "within the three cloud regions tested"; amplification forecasting scoped to "explains a substantial fraction of variance" rather than "single parameter forecast".
- Appendix Table 6 (per-region cache hit rates): regenerated from `full_400_sessions.csv` to match fresh libCacheSim replay exactly.

### Security / Anonymity
- Sanitization pipeline applied to all released data:
  - Stripped `Authorization` / `Cookie` / `Set-Cookie` / `Proxy-Authorization` headers (removed 121 leaked Basic-Auth credentials in prior-version traces).
  - Redacted all URL query parameter values to `_REDACTED_` (4,378 URLs in release subtree; 30,321 in canonical scripted CSV).
  - Replaced project-brand User-Agent strings with `BrowseTrace/1.0 (benchmark)`.
- Verified zero occurrences of forbidden anonymity tokens (`SpotAIfy`, `AgentWebBench`, `ASL-Project`, author surname) across release subtree and canonical CSVs.

### Removed
- Legacy `browseruse-live-v1` and `browseruse-live-v2` references from documentation. Those earlier releases are superseded by v3.
- `benchmark-paper.tex` filename references (paper source is now `BrowseTrace.tex`).

## [2.0] — 2026-04-08 (superseded)

Zurich scripted-random subset, 100 sessions, 14,833 requests. Published as `browseruse-live-v2`. Retained only within the v3 manifest's scripted subtree.

## [1.x] — 2026-03 (superseded)

Early prototype releases (`browseruse-live-v0`, `browseruse-live-v1`) used internal development and are no longer referenced by the paper.

---

## Planned

- **v4:** Include HTTP/2 multiplexing analysis, longitudinal re-collection every 6 months, broader task coverage (~20 families), interactive workflows for sites that permit agent authentication.
