"""
pipeline_telemetry.py
=====================
Structured per-analysis-id telemetry for the Grom OCR pipeline.

Usage inside ocr_agent.py
--------------------------
    from utils.pipeline_telemetry import PipelineTrace, get_telemetry_enabled

    if get_telemetry_enabled():
        trace = PipelineTrace(analysis_id)
    else:
        trace = PipelineTrace.__null__()

    with trace.span("input_load"):
        ...do work...

    with trace.span("ocr_ensemble", engine="easyocr"):
        ...do work...

    payload['telemetry'] = trace.to_dict()

Environment variables
---------------------
    GROM_TELEMETRY_ENABLED   - "1" / "true" to enable (default: "1")
    GROM_TELEMETRY_IN_PAYLOAD - "1" / "true" to embed telemetry in API response (default: "1")
    GROM_TELEMETRY_LOG_JSONL  - file path to append JSONL telemetry lines (optional)
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, Iterator, List, Optional


# ---------------------------------------------------------------------------
# Environment flags
# ---------------------------------------------------------------------------

def get_telemetry_enabled() -> bool:
    v = os.environ.get("GROM_TELEMETRY_ENABLED", "1").strip().lower()
    return v in ("1", "true", "yes")


def get_telemetry_in_payload() -> bool:
    v = os.environ.get("GROM_TELEMETRY_IN_PAYLOAD", "1").strip().lower()
    return v in ("1", "true", "yes")


def _telemetry_log_path() -> Optional[str]:
    p = os.environ.get("GROM_TELEMETRY_LOG_JSONL", "").strip()
    return p if p else None


# ---------------------------------------------------------------------------
# Span dataclass (plain dict for serialisability)
# ---------------------------------------------------------------------------

class PipelineSpan:
    __slots__ = (
        "stage", "start_ts", "end_ts", "duration_ms", "status",
        "meta", "error",
    )

    def __init__(self, stage: str, **meta: Any) -> None:
        self.stage = stage
        self.start_ts: float = time.monotonic()
        self.end_ts: Optional[float] = None
        self.duration_ms: Optional[float] = None
        self.status: str = "running"
        self.meta: Dict[str, Any] = dict(meta)
        self.error: Optional[str] = None

    def close(self, status: str = "ok", error: Optional[str] = None, **extra_meta: Any) -> None:
        self.end_ts = time.monotonic()
        self.duration_ms = round((self.end_ts - self.start_ts) * 1000, 2)
        self.status = status
        if error:
            self.error = str(error)
        self.meta.update(extra_meta)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "stage": self.stage,
            "duration_ms": self.duration_ms,
            "status": self.status,
        }
        if self.meta:
            d["meta"] = self.meta
        if self.error:
            d["error"] = self.error
        return d


# ---------------------------------------------------------------------------
# PipelineTrace
# ---------------------------------------------------------------------------

class PipelineTrace:
    """
    Tracks all spans for a single analysis_id request.

    Create one per request, add spans with the context-manager helper,
    then call ``to_dict()`` to get a serialisable telemetry block.
    """

    _null_instance: Optional["PipelineTrace"] = None

    def __init__(self, analysis_id: str, *, null: bool = False) -> None:
        self.analysis_id = analysis_id
        self._null = null
        self._spans: List[PipelineSpan] = []
        self._wall_start: float = time.time()
        self._mono_start: float = time.monotonic()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Null object pattern – avoids scattered ``if telemetry_enabled``
    # ------------------------------------------------------------------
    @classmethod
    def null(cls) -> "PipelineTrace":
        """Return a lightweight no-op trace (singleton)."""
        if cls._null_instance is None:
            cls._null_instance = cls("__null__", null=True)
        return cls._null_instance

    # ------------------------------------------------------------------
    # Span API
    # ------------------------------------------------------------------

    @contextmanager
    def span(self, stage: str, **meta: Any) -> Generator[PipelineSpan, None, None]:
        """Context manager that records a stage span."""
        if self._null:
            # No-op span – yield a dummy object
            dummy = PipelineSpan(stage, **meta)
            yield dummy
            return

        s = PipelineSpan(stage, **meta)
        try:
            yield s
            s.close(status="ok")
        except Exception as exc:
            s.close(status="error", error=str(exc))
            raise
        finally:
            if not self._null:
                with self._lock:
                    self._spans.append(s)

    def record(self, stage: str, duration_ms: float, status: str = "ok", **meta: Any) -> None:
        """Record a pre-computed span without using the context manager."""
        if self._null:
            return
        s = PipelineSpan(stage, **meta)
        s.duration_ms = round(duration_ms, 2)
        s.end_ts = s.start_ts + duration_ms / 1000
        s.status = status
        with self._lock:
            self._spans.append(s)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        if self._null:
            return {}
        total_ms = round((time.monotonic() - self._mono_start) * 1000, 2)
        return {
            "analysis_id": self.analysis_id,
            "total_duration_ms": total_ms,
            "spans": [s.to_dict() for s in self._spans],
        }

    # ------------------------------------------------------------------
    # JSONL log flush
    # ------------------------------------------------------------------

    def flush_to_log(self) -> None:
        """Append one JSONL line to GROM_TELEMETRY_LOG_JSONL if configured."""
        if self._null:
            return
        log_path = _telemetry_log_path()
        if not log_path:
            return
        try:
            entry = self.to_dict()
            entry["wall_start_utc"] = self._wall_start
            line = json.dumps(entry, ensure_ascii=False)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass  # telemetry must never crash the pipeline


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def make_trace(analysis_id: str) -> PipelineTrace:
    """Return an active trace if telemetry is enabled, else a null trace."""
    if get_telemetry_enabled():
        return PipelineTrace(analysis_id)
    return PipelineTrace.null()
