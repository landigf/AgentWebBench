# BrowseTrace Reproducibility Guide

This guide takes a fresh clone of the repository and reproduces every numeric claim in the IMC 2026 paper.

## System requirements

- macOS or Linux (tested on macOS 15 and Ubuntu 24.04)
- Python 3.11+ (3.12 tested)
- 8 GB RAM minimum, 16 GB recommended for LLM cache replay
- ~2 GB disk for the dataset

## Step 0: clone

```bash
curl -L -o BrowseTrace.zip https://anonymous.4open.science/api/repo/BrowseTrace/zip
unzip BrowseTrace.zip -d BrowseTrace
cd BrowseTrace
```

## Step 1: install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Key packages (pinned in `requirements.txt`):

- `libcachesim>=0.3.3` — reference cache simulator (C + Python bindings)
- `matplotlib`, `numpy`, `scipy` — analysis
- `pandas` — CSV manipulation (analysis scripts only)
- `browser-use` — optional, only for re-collection from scratch

## Step 2: verify canonical CSVs are present and clean

```bash
python3 verify_submission_gate.py
```

Expected output (summary line at the end):

```
Summary: N OK, 1 WARN, 0 FAIL
```

The single WARN is a documented scope-labelling clarification about the `release-v3` directory; it is not a reproducibility failure.

If you see any FAIL, do not proceed — the repo state is inconsistent with the paper.

## Step 3: reproduce the headline cache-policy numbers

```bash
python3 - <<'PY'
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
        mr, _ = cls(5 * 1024 * 1024).process_trace(r)
        print(f'{label:9s} {name:5s} @5MiB: {(1-mr)*100:.1f}%')
PY
```

Expected:

```
scripted LRU   @5MiB: 37.4%
scripted GDSF  @5MiB: 59.5%
llm      LRU   @5MiB: 43.5%
llm      GDSF  @5MiB: 76.2%
```

These match Table 5 (scripted) and the abstract (LLM) in the paper exactly.

## Step 4: reproduce Table 5 and the appendix per-region table (Table 6)

The full Table 5 sweep (LRU, LFU, ARC, S3-FIFO, W-TinyLFU, GDSF on
`full_400_sessions.csv` at 1, 5, 10, 25, 50 MiB) and the per-region
breakdown (splitting `full_400_sessions.csv` by `session_id` prefix
and replaying each region under libCacheSim) are both executed by
`verify_submission_gate.py`. Run that script and compare its
`replay` and `replay-region` lines against Table 5 and Table 6 in
the paper.

```bash
python3 verify_submission_gate.py
```

## Step 5: compile the paper

```bash
cd paper
latexmk -pdf -interaction=nonstopmode BrowseTrace.tex
```

Output: `BrowseTrace.pdf`, 16 pages (13 body, 1 page references, 2
pages appendices), letter paper.

## Step 6: full end-to-end gate

```bash
# From repo root
python3 paper/regenerate_full_snapshot.py   # rebuild artifact_snapshot.json
cd paper
latexmk -pdf -interaction=nonstopmode BrowseTrace.tex
python3 verify_submission_gate.py
```

Expected final summary: `0 FAIL`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `libcachesim` import error | Not installed, wrong Python | `pip install libcachesim` — verify version 0.3.3+ |
| Table numbers off by 0.001 | Different rounding in your printing | Paper rounds to 3 decimals; compute at full precision |
| Gate reports sanitization FAIL | A release subtree contains unscrubbed data | Run `python3 tools/sanitize_release.py <path-to-subtree>` then rerun gate |
| LaTeX compile fails | Missing `acmart` or fonts | `tlmgr install acmart` (TeX Live) or install Overleaf-style full distribution |

## Re-collecting from scratch (optional)

The released CSVs are sufficient for reproducing all paper numbers. To re-collect new sessions:

1. Set API keys: `export OPENAI_API_KEY=... GEMINI_API_KEY=... ANTHROPIC_API_KEY=...`
2. Check target sites' `robots.txt` for any changes since Feb-Apr 2026.
3. Run the collector:

```bash
python3 collection/runner.py --task all --surface live --live-driver agent \
                              --llm-model gpt-4.1-mini --repeats 5
```

4. Sanitize before sharing:

```bash
python3 tools/sanitize_release.py data/my-new-collection/
```

5. Build a new stitched cache trace by appending sanitized
   `cache_trace.csv` rows from the new collection into the canonical
   CSV under `data/traces/`, preserving the `time, obj_id, obj_size`
   schema used by libCacheSim.

## Contact

Issues: via the anonymous mirror at https://anonymous.4open.science/r/BrowseTrace (author contact published after IMC 2026 notification).
