"""Prometheus metrics for the chat pipeline.

All metrics are optional — if prometheus_client is not installed the
module exports no-op stubs so the rest of the app keeps working.
"""

import logging
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

    CHAT_QUERIES = Counter(
        "chat_query_total",
        "Total chat queries processed",
        ["status", "intent"],
    )

    CHAT_LLM_DURATION = Histogram(
        "chat_llm_duration_seconds",
        "LLM call latency by task role",
        ["role"],
        buckets=(0.5, 1, 2, 5, 10, 30, 60, 120),
    )

    CHAT_TABLE_SELECTION = Counter(
        "chat_table_selection_method",
        "Table selection outcome",
        ["method"],
    )

    CHAT_REPAIR_ATTEMPTS = Histogram(
        "chat_repair_attempts",
        "Number of SQL repair attempts per query",
        buckets=(0, 1, 2, 3),
    )

    CHAT_REPAIR_SUCCESS = Counter(
        "chat_repair_success_total",
        "Successful SQL repairs",
    )

    CHAT_CACHE_OPS = Counter(
        "chat_cache_ops_total",
        "Cache hit / miss / set operations",
        ["op"],
    )

    CHAT_QUERY_EXEC_DURATION = Histogram(
        "chat_query_exec_duration_seconds",
        "SQL execution time against user databases",
        buckets=(0.01, 0.05, 0.1, 0.5, 1, 5, 10, 30),
    )

    PROMETHEUS_AVAILABLE = True

except ImportError:
    PROMETHEUS_AVAILABLE = False
    generate_latest = None
    CONTENT_TYPE_LATEST = "text/plain"

    class _NoOp:
        """No-op metric stub."""
        def labels(self, *a, **kw):
            return self
        def inc(self, *a, **kw):
            pass
        def observe(self, *a, **kw):
            pass

    CHAT_QUERIES = _NoOp()
    CHAT_LLM_DURATION = _NoOp()
    CHAT_TABLE_SELECTION = _NoOp()
    CHAT_REPAIR_ATTEMPTS = _NoOp()
    CHAT_REPAIR_SUCCESS = _NoOp()
    CHAT_CACHE_OPS = _NoOp()
    CHAT_QUERY_EXEC_DURATION = _NoOp()

    logger.info("prometheus_client not installed — metrics disabled")


@contextmanager
def track_llm(role: str):
    """Context manager that records LLM call duration for *role*."""
    start = time.perf_counter()
    try:
        yield
    finally:
        CHAT_LLM_DURATION.labels(role=role).observe(time.perf_counter() - start)
