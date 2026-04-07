"""Standardized trace schema shared across all SpotAIfy tracks.

Used by:
- asl-project/instrumentation (trace capture)
- research/agent-traffic/traffic-gen (synthetic generation)
- research/agent-traffic/cache-sim (cache simulation input)
- dashboard/sample-data (access log generation)
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class AccessMode(str, Enum):
    SCRAPING = "scraping"
    MACHINE_LANE = "machine-lane"
    UNKNOWN = "unknown"


class AgentType(str, Enum):
    CRAWLER = "crawler"
    RAG = "rag"
    MULTI_STEP = "multi-step"
    HUMAN = "human"
    UNKNOWN = "unknown"


class TraceRequest(BaseModel):
    timestamp_us: int = 0
    url: str = ""
    method: str = "GET"
    status: int = 200
    request_headers: dict[str, str] = Field(default_factory=dict)
    response_size_bytes: int = 0
    content_type: str = ""
    latency_ms: float = 0.0
    session_id: str = ""
    task_id: str = ""
    access_mode: AccessMode = AccessMode.UNKNOWN
    agent_type: AgentType = AgentType.UNKNOWN
    agent_domain: str = ""
    purpose: str = ""
    cache_key: str = ""
    object_size_bytes: int = 0


class TraceSession(BaseModel):
    session_id: str
    task_id: str = ""
    task_name: str = ""
    agent_type: AgentType = AgentType.UNKNOWN
    access_mode: AccessMode = AccessMode.UNKNOWN
    start_time_us: int = 0
    end_time_us: int = 0
    requests: list[TraceRequest] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def total_bytes(self) -> int:
        return sum(r.response_size_bytes for r in self.requests)

    @property
    def total_requests(self) -> int:
        return len(self.requests)

    @property
    def unique_urls(self) -> int:
        return len({r.url for r in self.requests})

    @property
    def duration_ms(self) -> float:
        if not self.requests:
            return 0.0
        return (self.end_time_us - self.start_time_us) / 1000


class TraceFile(BaseModel):
    version: str = "0.1"
    generator: str = ""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    sessions: list[TraceSession] = Field(default_factory=list)

    @property
    def total_requests(self) -> int:
        return sum(s.total_requests for s in self.sessions)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str | Path) -> TraceFile:
        return cls.model_validate_json(Path(path).read_text())

    def to_cache_sim_csv(self, path: str | Path) -> None:
        """Export to CSV for cache simulators.
        Columns: timestamp_us, cache_key, object_size_bytes, session_id, agent_type
        """
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["timestamp_us", "cache_key", "object_size_bytes", "session_id", "agent_type"]
            )
            for session in self.sessions:
                for req in session.requests:
                    key = req.cache_key or req.url
                    size = req.object_size_bytes or req.response_size_bytes
                    writer.writerow(
                        [req.timestamp_us, key, size, session.session_id, session.agent_type.value]
                    )

    def to_access_log_jsonl(self, path: str | Path) -> None:
        """Export to JSONL access log format for the dashboard."""
        with open(path, "w") as f:
            for session in self.sessions:
                for req in session.requests:
                    entry = {
                        "timestamp": datetime.fromtimestamp(
                            req.timestamp_us / 1_000_000, tz=timezone.utc
                        ).isoformat(),
                        "ip": session.metadata.get("ip", "0.0.0.0"),
                        "method": req.method,
                        "path": req.url,
                        "status": req.status,
                        "response_size": req.response_size_bytes,
                        "user_agent": req.request_headers.get("user-agent", ""),
                        "agent_domain": req.agent_domain or None,
                        "agent_purpose": req.purpose or None,
                        "is_ai": req.agent_type != AgentType.HUMAN,
                        "session_id": session.session_id,
                        "content_type": req.content_type,
                        "latency_ms": req.latency_ms,
                    }
                    f.write(json.dumps(entry) + "\n")
