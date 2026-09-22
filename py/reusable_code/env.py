"""Environment loading shared by every LRM11 notebook.

Every notebook in this repo reads the same ``.env`` file at the project
root (created once from ``.env.sample``). Centralizing that here means a
typo in one notebook's copy-pasted ``require_env`` can't quietly drift from
the others -- there's exactly one copy of this logic now.
"""
import os
from typing import Optional

from dotenv import load_dotenv

_loaded = False


def ensure_env_loaded() -> None:
    """Call python-dotenv's load_dotenv() exactly once per kernel, no
    matter how many reusable_code functions (or notebooks importing it)
    ask for it."""
    global _loaded
    if not _loaded:
        load_dotenv()
        _loaded = True


def require_env(name: str) -> str:
    """Fetch an env var and fail with a clear, actionable message (naming
    the exact .env line to fill in) instead of a cryptic downstream error
    such as ``SupabaseException('supabase_key is required')``."""
    ensure_env_loaded()
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is empty in your .env file. Open .env in the py/ folder "
            f"and paste your actual value in after '{name}='."
        )
    return value


def optional_env(name: str, default: str = "") -> str:
    """Same as require_env, but returns `default` instead of raising when
    the variable is missing or blank -- for values that have a sensible
    fallback (e.g. SUPABASE_SERVICE_ROLE_KEY falling back to the anon key)."""
    ensure_env_loaded()
    return os.environ.get(name, default).strip()


_TRUE_VALUES = {"true", "1", "yes", "on"}
_FALSE_VALUES = {"false", "0", "no", "off"}


def optional_env_bool(name: str, default: bool) -> bool:
    """Same as optional_env, but parsed as a boolean feature flag (e.g.
    ``USE_HYBRID_SEARCH=True`` in .env) -- returns `default` when the
    variable is missing/blank, and raises on an unrecognized value rather
    than silently treating a typo as falsy."""
    raw = optional_env(name, "").lower()
    if not raw:
        return default
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise RuntimeError(
        f"{name} in your .env file is {raw!r}, which isn't a recognized "
        f"boolean -- use True/False (or 1/0, yes/no, on/off)."
    )


_UNLIMITED_VALUES = {"none", "all", "full", "unlimited", "no", "0"}


def optional_env_limit(name: str, default: Optional[int]) -> Optional[int]:
    """A positive integer limit from .env, or ``None`` meaning "no limit".

    Unset/blank -> ``default``; ``NONE`` / ``ALL`` / ``FULL`` / ``UNLIMITED`` / ``0`` -> ``None``;
    an integer -> that integer. Anything else raises (a typo must not silently become "no limit").
    """
    raw = optional_env(name, "").lower()
    if not raw:
        return default
    if raw in _UNLIMITED_VALUES:
        return None
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise RuntimeError(
            f"{name} in your .env file is {raw!r}: use a positive number of pages, or NONE for no limit."
        )
    return value


def optional_env_int(name: str, default: int, *, minimum: int = 1) -> int:
    """A plain positive integer from .env (unset/blank -> ``default``); raises on anything else, including
    a value below ``minimum``, so a typo can't silently turn into that default."""
    raw = optional_env(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = minimum - 1
    if value < minimum:
        raise RuntimeError(f"{name} in your .env file is {raw!r}: use an integer >= {minimum}.")
    return value
