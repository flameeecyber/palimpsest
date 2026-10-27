"""Optional Sentry tracing.

The partner category asks for latency, tokens, cost and debugging evidence.
When SENTRY_DSN is unset this module is a no-op, so the tool still runs with
the network off, which is the point.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any, Iterator

_ENABLED = False


def init(dsn: str | None = None) -> bool:
    global _ENABLED
    dsn = dsn or os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "1.0")),
            environment=os.environ.get("SENTRY_ENVIRONMENT", "palimpsest-local"),
            release=os.environ.get("PALIMPSEST_RELEASE", "0.1.0"),
            send_default_pii=False,
        )
        _ENABLED = True
        return True
    except Exception:  # pragma: no cover - tracing must never break a recovery
        return False


@contextlib.contextmanager
def span(op: str, **data: Any) -> Iterator[None]:
    if not _ENABLED:
        yield
        return
    try:
        import sentry_sdk

        with sentry_sdk.start_span(op=op, name=op) as current:
            for key, value in data.items():
                current.set_data(key, value)
            yield
    except Exception:  # pragma: no cover
        yield
