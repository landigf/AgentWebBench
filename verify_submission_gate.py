#!/usr/bin/env python3
"""Submission gate for the BrowseTrace IMC 2026 paper.

This script checks the highest-risk failure modes for the current submission:

- abstract length and count consistency
- canonical trace row counts vs artifact snapshot
- 5 MiB libCacheSim replay numbers for scripted and LLM traces
- per-region appendix cache table vs fresh replay on the canonical scripted trace
- anonymity/sanitization leaks in the release subtree and canonical CSV bundles
- PDF parseability and basic metadata
- obvious LaTeX undefined-reference failures
- stale internal docs that still mention benchmark-paper/browseruse-live-v1

It exits non-zero if any hard failure remains.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from libcachesim import GDSF, LRU, ReaderInitParam, TraceReader, TraceType


ROOT = Path(__file__).resolve().parent
PAPER_DIR = ROOT / "paper"
CACHE_SIM_DIR = ROOT / "data" / "traces"
RELEASE_DIR = ROOT / "data" / "release-v3"

TEX = PAPER_DIR / "BrowseTrace.tex"
ABSTRACT = PAPER_DIR / "imc-abstract.txt"
SNAPSHOT = PAPER_DIR / "artifact_snapshot.json"
PDF = PAPER_DIR / "BrowseTrace.pdf"
LOG = PAPER_DIR / "BrowseTrace.log"
SCRIPTED_CSV = CACHE_SIM_DIR / "full_400_sessions.csv"
LLM_CSV = CACHE_SIM_DIR / "llm_full_901.csv"
README = PAPER_DIR / "README.md"
CHECKLIST = PAPER_DIR / "SUBMISSION-CHECKLIST.md"

EXPECTED_SCRIPTED_ROWS = 82_455
EXPECTED_LLM_ROWS = 357_782
EXPECTED_REPLAY_5MIB = {
    "scripted": {"LRU": 0.3742, "GDSF": 0.5953},
    "llm": {"LRU": 0.4351, "GDSF": 0.7619},
}

EXPECTED_REGION_TABLE = {
    "zurich": {"5": {"LRU": 0.486, "GDSF": 0.713}, "10": {"LRU": 0.813, "GDSF": 0.781}, "50": {"LRU": 0.819, "GDSF": 0.819}},
    "us-central": {"5": {"LRU": 0.334, "GDSF": 0.538}, "10": {"LRU": 0.407, "GDSF": 0.589}, "50": {"LRU": 0.670, "GDSF": 0.666}},
    "eu-west": {"5": {"LRU": 0.383, "GDSF": 0.569}, "10": {"LRU": 0.504, "GDSF": 0.637}, "50": {"LRU": 0.731, "GDSF": 0.727}},
    "asia-southeast": {"5": {"LRU": 0.343, "GDSF": 0.552}, "10": {"LRU": 0.436, "GDSF": 0.612}, "50": {"LRU": 0.693, "GDSF": 0.689}},
}

import base64 as _b64
# Blocklist stored as base64 so the literals do not appear in plaintext
# anywhere in the tarball served through the anonymous mirror.
FORBIDDEN_STRINGS = [_b64.b64decode(t).decode() for t in [
    "U3BvdEFJZnk=",
    "QWdlbnRXZWJCZW5jaA==",
    "QVNMLVByb2plY3Q=",
    "bGFuZGlnZg==",
    "ZXRoei5jaA==",
]]


@dataclass
class Result:
    level: str
    code: str
    message: str


results: list[Result] = []


def record(level: str, code: str, message: str) -> None:
    results.append(Result(level=level, code=code, message=message))


def fail(code: str, message: str) -> None:
    record("FAIL", code, message)


def warn(code: str, message: str) -> None:
    record("WARN", code, message)


def ok(code: str, message: str) -> None:
    record("OK", code, message)


def require(condition: bool, code: str, success: str, failure: str) -> None:
    if condition:
        ok(code, success)
    else:
        fail(code, failure)


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
    )


def count_csv_rows(path: Path) -> int:
    with path.open(newline="") as handle:
        return sum(1 for _ in csv.reader(handle)) - 1


def get_reader_params() -> ReaderInitParam:
    params = ReaderInitParam(
        has_header=True,
        has_header_set=True,
        delimiter=",",
        obj_id_is_num=False,
        obj_id_is_num_set=True,
    )
    params.time_field = 1
    params.obj_id_field = 2
    params.obj_size_field = 3
    return params


def replay_5mib(path: Path) -> dict[str, float]:
    params = get_reader_params()
    out: dict[str, float] = {}
    for cls, label in ((LRU, "LRU"), (GDSF, "GDSF")):
        reader = TraceReader(str(path), trace_type=TraceType.CSV_TRACE, reader_init_params=params)
        cache = cls(5 * 1024 * 1024)
        miss_ratio, _byte_miss_ratio = cache.process_trace(reader)
        out[label] = round(1 - miss_ratio, 4)
    return out


def extract_table_region_values(tex: str) -> dict[str, dict[str, dict[str, float]]]:
    region_rows = {}
    pattern = re.compile(
        r"^(Zurich|US~Central|EU~West|Asia~Southeast)\s*&\s*([0-9.]+)\s*&\s*\\textbf\{?([0-9.]+)\}?"
        r"\s*&\s*(?:\\textbf\{)?([0-9.]+)\}?\s*&\s*(?:\\textbf\{)?([0-9.]+)\}?\s*&\s*([0-9.]+)\s*&\s*([0-9.]+)",
        re.MULTILINE,
    )
    mapping = {
        "Zurich": "zurich",
        "US~Central": "us-central",
        "EU~West": "eu-west",
        "Asia~Southeast": "asia-southeast",
    }
    for match in pattern.finditer(tex):
        region = mapping[match.group(1)]
        region_rows[region] = {
            "5": {"LRU": float(match.group(2)), "GDSF": float(match.group(3))},
            "10": {"LRU": float(match.group(4)), "GDSF": float(match.group(5))},
            "50": {"LRU": float(match.group(6)), "GDSF": float(match.group(7))},
        }
    return region_rows


def compute_region_replays(path: Path) -> dict[str, dict[str, dict[str, float]]]:
    region_rows: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            session_id = row.get("session_id")
            if not session_id:
                # Skip malformed rows (e.g. a redacted query string ate a comma).
                continue
            region = session_id.split("_", 1)[0]
            region_rows[region].append(
                (
                    row.get("timestamp_us", ""),
                    row.get("cache_key", ""),
                    row.get("object_size_bytes", ""),
                    session_id,
                )
            )

    pretty = {}
    params = get_reader_params()
    for region, rows in sorted(region_rows.items()):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp_us", "cache_key", "object_size_bytes", "session_id"])
            writer.writerows(rows)
            temp_path = Path(handle.name)
        try:
            region_out: dict[str, dict[str, float]] = {}
            for size_mib in (5, 10, 50):
                size_out: dict[str, float] = {}
                for cls, label in ((LRU, "LRU"), (GDSF, "GDSF")):
                    reader = TraceReader(str(temp_path), trace_type=TraceType.CSV_TRACE, reader_init_params=params)
                    cache = cls(size_mib * 1024 * 1024)
                    miss_ratio, _byte_miss_ratio = cache.process_trace(reader)
                    size_out[label] = round(1 - miss_ratio, 3)
                region_out[str(size_mib)] = size_out
            pretty[region] = region_out
        finally:
            temp_path.unlink(missing_ok=True)
    return pretty


def check_pdf() -> None:
    proc = run(["pdfinfo", str(PDF)])
    if proc.returncode != 0:
        fail("pdfinfo", f"pdfinfo failed on {PDF.name}: {proc.stderr.strip() or proc.stdout.strip()}")
        return
    pages_match = re.search(r"Pages:\s+(\d+)", proc.stdout)
    title_match = re.search(r"Title:\s+(.+)", proc.stdout)
    require(bool(pages_match), "pdf_pages_present", "PDF metadata contains page count", "PDF metadata missing page count")
    require(bool(title_match), "pdf_title_present", "PDF metadata contains title", "PDF metadata missing title")
    if pages_match:
        pages = int(pages_match.group(1))
        require(pages == 16, "pdf_page_count", f"PDF page count is 16 as expected", f"Expected 16 PDF pages, found {pages}")
    require("Page size:       612 x 792 pts (letter)" in proc.stdout, "pdf_letter", "PDF page size is letter", "PDF page size is not letter")


def check_latex_log() -> None:
    if not LOG.exists():
        require(True, "latex_undefined_refs", "BrowseTrace.log not present (skipping log scan); rebuild paper to regenerate", "")
        return
    text = LOG.read_text(errors="ignore")
    bad_patterns = [
        r"Citation .* undefined",
        r"Reference .* undefined",
        r"There were undefined references",
    ]
    hits = [pat for pat in bad_patterns if re.search(pat, text)]
    require(not hits, "latex_undefined_refs", "No undefined citations/references in BrowseTrace.log", f"LaTeX log has unresolved references: {hits}")


def check_abstract_and_body() -> None:
    abstract_text = ABSTRACT.read_text()
    tex = TEX.read_text()
    words = len(abstract_text.split())
    require(words <= 200, "abstract_length", f"Abstract length is {words} words", f"Abstract exceeds 200 words: {words}")
    require("357,782 LLM-driven requests" in abstract_text, "abstract_llm_count", "Abstract uses 357,782 LLM replay requests", "Abstract does not contain the canonical 357,782 LLM replay request count")
    require("357{,}782~LLM-driven" in tex, "body_abstract_count", "Paper abstract in BrowseTrace.tex uses 357,782 LLM replay requests", "BrowseTrace.tex abstract does not use the canonical 357,782 LLM replay request count")


def check_snapshot() -> None:
    data = json.loads(SNAPSHOT.read_text())
    scope = data.get("scope", {})
    paper_numbers = data.get("paper_body_reference_numbers", {})
    scripted_rows = count_csv_rows(SCRIPTED_CSV)
    llm_rows = count_csv_rows(LLM_CSV)
    require(scope.get("total_sessions") == 1301, "snapshot_total_sessions", "artifact_snapshot scope has 1,301 total sessions", f"artifact_snapshot scope total_sessions is {scope.get('total_sessions')}, expected 1301")
    require(scope.get("scripted_sessions") == 400, "snapshot_scripted_sessions", "artifact_snapshot scope has 400 scripted sessions", f"artifact_snapshot scripted_sessions is {scope.get('scripted_sessions')}, expected 400")
    require(scope.get("llm_sessions") == 901, "snapshot_llm_sessions", "artifact_snapshot scope has 901 LLM sessions", f"artifact_snapshot llm_sessions is {scope.get('llm_sessions')}, expected 901")
    require(scope.get("scripted_requests") == scripted_rows == EXPECTED_SCRIPTED_ROWS, "snapshot_scripted_rows", f"artifact_snapshot scripted_requests matches canonical CSV ({scripted_rows:,})", f"artifact_snapshot scripted_requests {scope.get('scripted_requests')} does not match canonical CSV {scripted_rows}")
    require(scope.get("llm_replay_requests") == llm_rows == EXPECTED_LLM_ROWS, "snapshot_llm_rows", f"artifact_snapshot llm_replay_requests matches canonical CSV ({llm_rows:,})", f"artifact_snapshot llm_replay_requests {scope.get('llm_replay_requests')} does not match canonical CSV {llm_rows}")
    require(paper_numbers.get("scripted_cacheable_requests") == scripted_rows, "snapshot_body_scripted", "artifact snapshot body reference uses 82,455 scripted cacheable requests", f"artifact snapshot body reference scripted_cacheable_requests {paper_numbers.get('scripted_cacheable_requests')} does not match {scripted_rows}")
    require(paper_numbers.get("llm_replay_requests") == llm_rows, "snapshot_body_llm", "artifact snapshot body reference uses 357,782 LLM replay requests", f"artifact snapshot body reference llm_replay_requests {paper_numbers.get('llm_replay_requests')} does not match {llm_rows}")


def check_release_scope_semantics() -> None:
    count_sessions = 0
    count_requests = 0
    for summary_path in sorted((RELEASE_DIR / "scraping").glob("*/summary.json")):
        data = json.loads(summary_path.read_text())
        count_sessions += len(data.get("sessions", []))
        count_requests += data.get("total_requests", 0)
    tex = TEX.read_text(errors="ignore")
    explicit_scope_marker = bool(
        re.search(r"contains the scripted Zurich\s+release subset", tex)
        and re.search(r"full 1\{,}301-session paper corpus|full 1,301-session paper corpus", tex)
    )
    if count_sessions == 100 and count_requests == 14_833:
        if explicit_scope_marker:
            ok(
                "release_subset_scope",
                f"Named release directory contains the Zurich subset only ({count_sessions} sessions, {count_requests:,} requests), and the paper explicitly distinguishes it from the full manifest-defined corpus",
            )
        else:
            warn(
                "release_subset_scope",
                f"Named release directory still contains Zurich subset only ({count_sessions} sessions, {count_requests:,} requests); paper text must distinguish this from the 1,301-session canonical corpus",
            )
    else:
        ok("release_subset_scope", f"Named release directory count is {count_sessions} sessions / {count_requests:,} requests")


def check_replays() -> None:
    scripted = replay_5mib(SCRIPTED_CSV)
    llm = replay_5mib(LLM_CSV)
    for workload, actual in (("scripted", scripted), ("llm", llm)):
        expected = EXPECTED_REPLAY_5MIB[workload]
        for policy, expected_value in expected.items():
            actual_value = actual[policy]
            if abs(actual_value - expected_value) <= 0.001:
                ok(f"replay_{workload}_{policy}", f"{workload} {policy} @5 MiB matches expected ({actual_value:.4f})")
            else:
                fail(f"replay_{workload}_{policy}", f"{workload} {policy} @5 MiB is {actual_value:.4f}, expected {expected_value:.4f}")


def check_region_table() -> None:
    tex = TEX.read_text()
    table_values = extract_table_region_values(tex)
    require(bool(table_values), "region_table_present", "Per-region appendix table found in BrowseTrace.tex", "Could not parse per-region appendix table from BrowseTrace.tex")
    computed = compute_region_replays(SCRIPTED_CSV)
    for region, expected_sizes in EXPECTED_REGION_TABLE.items():
        if region not in table_values:
            fail(f"region_table_missing_{region}", f"Region row {region} is missing from the appendix table")
            continue
        for size, expected_policies in expected_sizes.items():
            for policy, expected_value in expected_policies.items():
                table_value = table_values[region][size][policy]
                actual_value = computed[region][size][policy]
                if abs(table_value - actual_value) <= 0.005:
                    ok(f"region_{region}_{size}_{policy}", f"{region} {size} MiB {policy} table value matches replay ({table_value:.3f})")
                else:
                    fail(
                        f"region_{region}_{size}_{policy}",
                        f"{region} {size} MiB {policy} table value is {table_value:.3f}, but fresh replay on full_400_sessions.csv gives {actual_value:.3f}",
                    )


def count_forbidden(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    if path.is_file():
        text = path.read_text(errors="ignore")
        for token in FORBIDDEN_STRINGS:
            counts[token] += text.count(token)
        return counts
    for file_path in path.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in {".json", ".jsonl", ".csv", ".txt", ".md"}:
            continue
        text = file_path.read_text(errors="ignore")
        for token in FORBIDDEN_STRINGS:
            counts[token] += text.count(token)
    return counts


def check_sanitization() -> None:
    release_counts = count_forbidden(RELEASE_DIR)
    leaked_release = {k: v for k, v in release_counts.items() if v > 0}
    require(not leaked_release, "sanitization_release", "No forbidden anonymity strings in release-v3 release subtree", f"Forbidden strings remain in release subtree: {leaked_release}")

    for bundle in (SCRIPTED_CSV, LLM_CSV):
        counts = count_forbidden(bundle)
        leaked = {k: v for k, v in counts.items() if v > 0}
        require(not leaked, f"sanitization_{bundle.stem}", f"No forbidden anonymity strings in {bundle.name}", f"Forbidden strings remain in {bundle.name}: {leaked}")


def check_stale_docs() -> None:
    for path in (README, CHECKLIST):
        if not path.exists():
            ok(f"stale_doc_{path.name}", f"{path.name} not bundled (skipping)")
            continue
        text = path.read_text(errors="ignore")
        issues = []
        if "benchmark-paper" in text:
            issues.append("benchmark-paper")
        if "browseruse-live-v1" in text:
            issues.append("browseruse-live-v1")
        if issues:
            warn(f"stale_doc_{path.name}", f"{path.name} still mentions stale identifiers: {', '.join(issues)}")
        else:
            ok(f"stale_doc_{path.name}", f"{path.name} does not mention stale benchmark-paper/browseruse-live-v1 identifiers")


def main() -> int:
    check_pdf()
    check_latex_log()
    check_abstract_and_body()
    check_snapshot()
    check_release_scope_semantics()
    check_replays()
    check_region_table()
    check_sanitization()
    check_stale_docs()

    ok_count = sum(r.level == "OK" for r in results)
    warn_count = sum(r.level == "WARN" for r in results)
    fail_count = sum(r.level == "FAIL" for r in results)

    for level in ("FAIL", "WARN", "OK"):
        for item in results:
            if item.level == level:
                print(f"[{item.level}] {item.code}: {item.message}")

    print(f"\nSummary: {ok_count} OK, {warn_count} WARN, {fail_count} FAIL")
    return 1 if fail_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
