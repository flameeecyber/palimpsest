"""Optional tracing: the same spans to Sentry, or to stderr.

The partner category asks for latency, tokens, cost and debugging evidence.
Two sinks, one call site:

- `SENTRY_DSN` set  → spans go to Sentry, with counts and durations only.
- `PALIMPSEST_TRACE=1` → the same spans are printed to stderr, so the tracing
  claim can be checked on a machine with no network and no account.
- neither → a no-op, which is the default and the point of the project.

Nothing here ever sends a filename, an evidence value or the contents of a
recovered file. A span knows how many artifacts it saw, not what they were.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
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


def local_enabled() -> bool:
    """Read the env at call time so a test can turn the printer on."""
    return os.environ.get("PALIMPSEST_TRACE", "").lower() not in ("", "0", "false", "no")


def _report(op: str, data: dict[str, Any], seconds: float) -> None:
    if not local_enabled():
        return
    fields = " ".join(f"{k}={v}" for k, v in data.items())
    print(f"[span] {op:<22} {fields} {seconds * 1000:.0f}ms", file=sys.stderr)


@contextlib.contextmanager
def span(op: str, **data: Any) -> Iterator[None]:
    started = time.perf_counter()
    try:
        # ExitStack, not a nested `with`: if Sentry cannot start a span the body
        # still runs, and an exception from the body is never swallowed.
        with contextlib.ExitStack() as stack:
            if _ENABLED:
                try:
                    import sentry_sdk

                    current = stack.enter_context(sentry_sdk.start_span(op=op, name=op))
                    for key, value in data.items():
                        current.set_data(key, value)
                except Exception:  # pragma: no cover
                    pass
            yield
    finally:
        _report(op, data, time.perf_counter() - started)
