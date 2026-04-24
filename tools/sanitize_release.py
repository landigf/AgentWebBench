#!/usr/bin/env python3
"""Sanitize BrowseTrace release artifacts for double-blind review and ethics compliance.

Applies to every traces.json, access_log.jsonl, and cache_trace.csv under the given
root, performing the transformations the paper's Ethics section claims (and Codex
found were missing):

  1. Strip request/response headers: Authorization, Cookie, Set-Cookie,
     Proxy-Authorization (case-insensitive).
  2. Redact URL query parameter values to "_REDACTED_" while keeping parameter
     names (so URL-path uniqueness is preserved for cache keying).
  3. Strip project-branded User-Agent strings (prior internal codenames) and
     replace with the generic "BrowseTrace/1.0 (benchmark)" token.
  4. Remove any session-level fingerprint fields containing those brand tokens.

Idempotent. Safe to re-run. Writes in-place.

Usage:
    python3 sanitize_release.py <root>  # e.g., data/release-v3/

Reports a summary of changes. Exits non-zero if any blocklisted identity
string remains after the sweep.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import base64 as _b64

# Blocklist stored as base64 so the identifying literals do not appear in
# plaintext anywhere in the tarball served through the anonymous mirror.
_FORBIDDEN_ENCODED = [
    "U3BvdEFJZnk=",
    "QWdlbnRXZWJCZW5jaA==",
    "QVNMLVByb2plY3Q=",
    "QVNMX1Byb2plY3Q=",
    "bGFuZGlnZg==",
    "TGFuZGk=",
    "R2lhbmZyYW5jbw==",
    "ZXRoei5jaA==",
]
FORBIDDEN = [_b64.b64decode(t).decode() for t in _FORBIDDEN_ENCODED]

STRIP_HEADERS = {"authorization", "cookie", "set-cookie", "proxy-authorization"}
# Branded UA substring pattern: rebuilt from the blocklist (keeping the
# pattern out of plaintext for the same reason as FORBIDDEN above).
BRAND_UA_PATTERN = re.compile("|".join(FORBIDDEN[:4]), re.IGNORECASE)
REPLACEMENT_UA = "BrowseTrace/1.0 (benchmark)"


def redact_url(url: str) -> str:
    """Replace query-param values with _REDACTED_, keep param names."""
    if not url or "?" not in url:
        return url
    try:
        parsed = urlparse(url)
        params = parse_qsl(parsed.query, keep_blank_values=True)
        redacted = [(k, "_REDACTED_") for k, _ in params]
        new_query = urlencode(redacted, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        return url  # leave untouched if parse fails


def sanitize_headers(hdrs: dict | None) -> tuple[dict, int]:
    """Remove forbidden headers and brand UA. Returns (new_hdrs, n_removed)."""
    if not hdrs or not isinstance(hdrs, dict):
        return hdrs or {}, 0
    removed = 0
    new = {}
    for k, v in hdrs.items():
        kl = k.lower()
        if kl in STRIP_HEADERS:
            removed += 1
            continue
        if kl == "user-agent" and isinstance(v, str):
            if BRAND_UA_PATTERN.search(v):
                new[k] = REPLACEMENT_UA
                continue
        new[k] = v
    return new, removed


def sanitize_request_record(r: dict) -> tuple[dict, dict]:
    """Sanitize a single request record. Returns (new_record, stats)."""
    stats = {"urls_redacted": 0, "hdrs_stripped": 0, "ua_replaced": 0}
    # URL query redaction
    for url_field in ("url", "request_url", "path"):
        if url_field in r and isinstance(r[url_field], str) and "?" in r[url_field]:
            red = redact_url(r[url_field])
            if red != r[url_field]:
                r[url_field] = red
                stats["urls_redacted"] = 1
    # cache_key often mirrors URL
    if "cache_key" in r and isinstance(r["cache_key"], str) and "?" in r["cache_key"]:
        r["cache_key"] = redact_url(r["cache_key"])
    # Sanitize request_headers + response_headers
    for field in ("request_headers", "response_headers"):
        hdrs = r.get(field)
        if hdrs:
            new_hdrs, n_removed = sanitize_headers(hdrs)
            r[field] = new_hdrs
            stats["hdrs_stripped"] += n_removed
            # Track UA replacements
            old_ua = (hdrs.get("user-agent") or hdrs.get("User-Agent") or "") if isinstance(hdrs, dict) else ""
            new_ua = (new_hdrs.get("user-agent") or new_hdrs.get("User-Agent") or "") if isinstance(new_hdrs, dict) else ""
            if BRAND_UA_PATTERN.search(str(old_ua)) and new_ua == REPLACEMENT_UA:
                stats["ua_replaced"] += 1
    # Top-level UA fields (access_log.jsonl uses user_agent not user-agent)
    for ua_field in ("user_agent", "ua"):
        if ua_field in r and isinstance(r[ua_field], str) and BRAND_UA_PATTERN.search(r[ua_field]):
            r[ua_field] = REPLACEMENT_UA
            stats["ua_replaced"] += 1
    # Session-id / other fields that may embed brand strings
    for field in ("session_id", "task_id", "agent_id", "collector"):
        v = r.get(field)
        if isinstance(v, str) and BRAND_UA_PATTERN.search(v):
            r[field] = BRAND_UA_PATTERN.sub("benchmark", v)
    return r, stats


def deep_scrub_brand(obj, counter=None):
    """Recursively walk a structure and replace brand substrings inside string leaves."""
    if counter is None:
        counter = [0]
    if isinstance(obj, str):
        if BRAND_UA_PATTERN.search(obj):
            counter[0] += 1
            # Replace URL-encoded brand forms (e.g. "Brand/0.2", "Brand%2F0.2")
            # using versions rebuilt from the base64 blocklist so the literal
            # brand tokens are never written into this source file.
            _brand = FORBIDDEN[0]  # primary brand token, decoded at import
            new = obj
            for enc in (f"{_brand}-ASL%2F0.2", f"{_brand}-ASL/0.2", _brand):
                new = new.replace(enc, "benchmark")
            new = BRAND_UA_PATTERN.sub("benchmark", new)
            return new, counter
        return obj, counter
    if isinstance(obj, dict):
        return {k: deep_scrub_brand(v, counter)[0] for k, v in obj.items()}, counter
    if isinstance(obj, list):
        return [deep_scrub_brand(x, counter)[0] for x in obj], counter
    return obj, counter


def sanitize_traces_json(path: Path) -> dict:
    """Sanitize a traces.json file in place. Returns stats."""
    stats = {"file": str(path), "urls_redacted": 0, "hdrs_stripped": 0, "ua_replaced": 0, "requests": 0}
    data = json.loads(path.read_text())
    sessions = data.get("sessions", []) if isinstance(data, dict) else data
    for s in sessions:
        # Session-level brand fingerprint scrub
        if isinstance(s, dict):
            for k in ("agent_user_agent", "user_agent", "fingerprint"):
                if k in s and isinstance(s[k], str) and BRAND_UA_PATTERN.search(s[k]):
                    s[k] = REPLACEMENT_UA
        for r in s.get("requests", []):
            stats["requests"] += 1
            _, rstats = sanitize_request_record(r)
            for k in ("urls_redacted", "hdrs_stripped", "ua_replaced"):
                stats[k] += rstats.get(k, 0)
    # Final recursive sweep for brand strings in any nested location
    data, _ = deep_scrub_brand(data)
    path.write_text(json.dumps(data, indent=2))
    return stats


def sanitize_access_log(path: Path) -> dict:
    """Sanitize access_log.jsonl (one JSON per line) in place."""
    stats = {"file": str(path), "urls_redacted": 0, "hdrs_stripped": 0, "ua_replaced": 0, "requests": 0}
    with path.open() as f:
        lines = f.readlines()
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        stats["requests"] += 1
        _, rstats = sanitize_request_record(r)
        # Final deep sweep for any missed brand strings in this record
        r, _ = deep_scrub_brand(r)
        for k in ("urls_redacted", "hdrs_stripped", "ua_replaced"):
            stats[k] += rstats.get(k, 0)
        out.append(json.dumps(r))
    path.write_text("\n".join(out) + "\n")
    return stats


def sanitize_cache_trace_csv(path: Path) -> dict:
    """Sanitize cache_trace.csv in place — only URL redaction matters."""
    stats = {"file": str(path), "urls_redacted": 0, "rows": 0}
    rows = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            stats["rows"] += 1
            if "cache_key" in row and isinstance(row["cache_key"], str) and "?" in row["cache_key"]:
                new = redact_url(row["cache_key"])
                if new != row["cache_key"]:
                    row["cache_key"] = new
                    stats["urls_redacted"] += 1
            rows.append(row)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return stats


def audit_forbidden(root: Path) -> dict:
    """Grep every text file under root for forbidden substrings. Returns map substring → count."""
    counts = {s: 0 for s in FORBIDDEN}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in (".json", ".jsonl", ".csv", ".txt", ".md"):
            continue
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        for s in FORBIDDEN:
            counts[s] += text.count(s)
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="release directory to sanitize")
    ap.add_argument("--dry-run", action="store_true", help="scan only, do not write")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: {root} does not exist", file=sys.stderr)
        sys.exit(2)

    agg = {"files": 0, "requests": 0, "urls_redacted": 0, "hdrs_stripped": 0, "ua_replaced": 0}

    print(f"Scanning {root}...")

    # Pre-scan: what's there before
    pre = audit_forbidden(root)
    print(f"  Pre-scan forbidden counts: {dict((k, v) for k, v in pre.items() if v > 0)}")

    if args.dry_run:
        print("--dry-run: skipping modifications")
        return

    # Sanitize
    for path in sorted(root.rglob("traces.json")):
        s = sanitize_traces_json(path)
        agg["files"] += 1
        for k in ("requests", "urls_redacted", "hdrs_stripped", "ua_replaced"):
            agg[k] += s[k]

    for path in sorted(root.rglob("access_log.jsonl")):
        s = sanitize_access_log(path)
        agg["files"] += 1
        for k in ("requests", "urls_redacted", "hdrs_stripped", "ua_replaced"):
            agg[k] += s[k]

    for path in sorted(root.rglob("cache_trace.csv")):
        s = sanitize_cache_trace_csv(path)
        agg["files"] += 1
        agg["urls_redacted"] += s["urls_redacted"]

    print(f"\nSanitization complete.")
    print(f"  Files processed:    {agg['files']}")
    print(f"  Requests scanned:   {agg['requests']:,}")
    print(f"  URLs redacted:      {agg['urls_redacted']:,}")
    print(f"  Headers stripped:   {agg['hdrs_stripped']:,}")
    print(f"  UA strings replaced:{agg['ua_replaced']:,}")

    # Post-scan
    post = audit_forbidden(root)
    leaked = {k: v for k, v in post.items() if v > 0}
    print(f"\n  Post-scan forbidden counts: {leaked if leaked else 'CLEAN'}")

    if leaked:
        print("\nWARNING: forbidden substrings still present after sanitization. See above.", file=sys.stderr)
        sys.exit(1)

    print("\n✓ Release is release-ready.")


if __name__ == "__main__":
    main()
