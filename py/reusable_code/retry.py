"""Exponential-backoff retry wrapper shared by every LRM11 notebook that
calls a flaky network API (Voyage, Supabase, Anthropic)."""
import random
import time
from typing import Callable, Optional, TypeVar

T = TypeVar("T")


def with_retry(
    fn: Callable[..., T],
    *args,
    max_attempts: int = 5,
    base_delay: float = 2.0,
    is_retryable: Optional[Callable[[Exception], bool]] = None,
    **kwargs,
) -> T:
    """Call ``fn(*args, **kwargs)``, retrying on exception with exponential
    backoff + jitter.

    ``is_retryable(exc)`` can be supplied to fail fast on errors retrying
    can never fix (e.g. lrm_child_chunk_table upload's non-retryable Postgrest error codes for
    bad data) -- it defaults to "everything is retryable", matching the
    original per-notebook ``_retry`` helpers this replaces.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 -- deliberately broad: network calls fail in many ways
            last_exc = e
            if is_retryable is not None and not is_retryable(e):
                raise
            if attempt == max_attempts:
                break
            sleep_s = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            print(
                f"[retry] {getattr(fn, '__name__', fn)} attempt {attempt} "
                f"failed ({e}); retrying in {sleep_s:.1f}s"
            )
            time.sleep(sleep_s)
    assert last_exc is not None
    raise last_exc


# Backward-compatible alias: every stage1_2/stage1_9/stage2 notebook already
# calls a private, per-notebook function literally named `_retry`. Keeping
# this alias means a notebook can switch to `from reusable_code import
# with_retry as _retry` and change nothing else about its call sites.
_retry = with_retry
