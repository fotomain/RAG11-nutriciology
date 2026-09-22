"""Shared client construction for every LRM11 notebook:
one Supabase client, one Voyage AI client, one Anthropic client, built the
same way everywhere instead of being copy-pasted -- and silently drifting
-- into each notebook.
"""
from dataclasses import dataclass
from typing import Dict

import anthropic
import voyageai
from supabase import Client as SupabaseClient
from supabase import create_client

from .env import optional_env, require_env

# Model ids -- change here once, every notebook that imports reusable_code
# picks it up.
EMBEDDING_MODEL = "voyage-3"  # must match the model used when lrm_child_chunk_table rows are embedded
RERANK_MODEL = "rerank-2"  # Voyage's cross-encoder reranker -- see retrieval.rerank_chunks()
GENERATION_MODEL = "claude-sonnet-5"  # change here if your account uses a different Claude model id


@dataclass(frozen=True)
class Clients:
    """A bundle of the three third-party clients every LRM11 notebook
    needs. Passed explicitly to reusable_code functions in tests (so they
    can be swapped for fakes with no network calls); picked up implicitly
    via get_clients() in notebooks."""

    supabase: SupabaseClient
    voyage: voyageai.Client
    anthropic: anthropic.Anthropic


_cache: Dict[str, Clients] = {}


def make_supabase_client() -> SupabaseClient:
    """Supabase client from .env. Prefers the service_role key (bypasses RLS cleanly); falls back to the
    anon key, which only works with the permissive policies sql/create_lrm_tables.sql sets up."""
    url = require_env("PUBLIC_SUPABASE_URL")
    key = optional_env("SUPABASE_SERVICE_ROLE_KEY") or require_env("PUBLIC_SUPABASE_ANON_KEY")
    return create_client(url, key)


def make_voyage_client() -> voyageai.Client:
    return voyageai.Client(api_key=require_env("VOYAGE_API_KEY"))


def init_clients(*, force: bool = False) -> Clients:
    """Build (or return the already-cached) Supabase/Voyage/Anthropic
    clients for this kernel.

    Call this once near the top of a notebook, right after
    ``from reusable_code import init_clients`` -- every other
    reusable_code function will use these same clients unless you
    explicitly pass a different ``clients=`` bundle to it. Safe to call
    again later (e.g. in a fresh cell after editing .env); pass
    ``force=True`` to rebuild rather than reuse the cached bundle.
    """
    if not force and "bundle" in _cache:
        return _cache["bundle"]

    bundle = Clients(
        supabase=make_supabase_client(),
        voyage=make_voyage_client(),
        anthropic=anthropic.Anthropic(api_key=require_env("ANTHROPIC_API_KEY")),
    )
    _cache["bundle"] = bundle
    return bundle


def get_clients() -> Clients:
    """Return the clients built by init_clients(). Raises a clear error
    (rather than a confusing AttributeError deep inside a retrieval call)
    if init_clients() hasn't run yet in this kernel."""
    if "bundle" not in _cache:
        raise RuntimeError(
            "No clients initialized yet -- call reusable_code.init_clients() "
            "near the top of your notebook first (or pass clients=... "
            "explicitly to this function)."
        )
    return _cache["bundle"]
