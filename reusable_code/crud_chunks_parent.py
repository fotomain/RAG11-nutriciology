"""CRUD operations for ``rag11_chunks_parent_table`` (one row per
section/parent chunk -- see ``sql/create_sql_tables.sql``).

This is the row-level counterpart to what ``stage1_2_eda_load_chunks.ipynb``
does inline for bulk ingestion: same row shape (``rowGUID`` / rowOwnerGUID``
/ ``rowParentGUID`` / ``orderInList`` / ``rowJSON``), same deterministic
``uuid5`` id scheme (so re-creating a parent chunk with the same
``parent_id`` is idempotent), but exposed as small, independently callable
functions instead of one-shot notebook cells -- for any notebook or script
that needs to create, read, update, or delete a single parent row (or a
handful of them) without re-running the whole Stage 1.2 pipeline.

Every public function name is prefixed ``create_``, ``read_``, ``update_``,
or ``delete_``, naming the CRUD operation it performs.

``crud_chunks_child.py`` imports ``deterministic_uuid``/``RAG11_UUID_NAMESPACE``
from here, since both tables share the same uuid5 namespace.
"""
import uuid
from typing import Iterable, List, Optional

from .clients import Clients, get_clients
from .retry import with_retry

PARENT_TABLE = "rag11_chunks_parent_table"

# Same namespace/seed as stage1_1_extract_and_chunk.ipynb, stage1_2, and
# stage1_9 -- must stay identical everywhere, or "the same" business key
# (e.g. a given parent_id) would deterministically hash to a different
# rowGUID depending on which code created it.
RAG11_UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "rag11.nutrition.poc")


def deterministic_uuid(business_key: str) -> str:
    """Derive a stable rowGUID from a business key (e.g. ``"parent:" +
    parent_id``), so creating the same logical row twice never duplicates
    it."""
    return str(uuid.uuid5(RAG11_UUID_NAMESPACE, business_key))


def _batched(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def create_parent_payload(data: dict, order: int, *, owner_guid: Optional[str] = None) -> dict:
    """Build one ``rag11_chunks_parent_table`` row dict from a
    ``parent_chunk-N.json``-shaped payload, without writing it anywhere.

    ``data`` must contain ``"parent_id"`` (the stable business key its
    ``rowGUID`` is derived from). ``owner_guid`` is the owning source's
    ``rag11_data_sources.rowGUID``; if omitted, it's read from
    ``data["source_row_guid"]`` (the field stage1_1_extract_and_chunk.ipynb
    writes into every chunk file).
    """
    resolved_owner = owner_guid or data.get("source_row_guid")
    if not resolved_owner:
        raise ValueError(
            "No owner_guid given and data has no 'source_row_guid' -- pass "
            "owner_guid explicitly (the parent chunk's rag11_data_sources rowGUID)."
        )
    return {
        "rowGUID": deterministic_uuid(f"parent:{data['parent_id']}"),
        "rowOwnerGUID": resolved_owner,
        "rowParentGUID": None,
        "orderInList": order,
        "rowJSON": data,
    }


def create_parent_rows(
    rows: Iterable[dict],
    *,
    batch_size: int = 100,
    clients: Optional[Clients] = None,
) -> int:
    """Upsert already-built parent row dicts (see ``create_parent_payload``)
    into ``rag11_chunks_parent_table``, in batches of ``batch_size``. Upsert
    (not plain insert) means calling this again with the same rows is
    always safe.

    Returns the number of rows sent (not necessarily the number changed).
    """
    clients = clients or get_clients()
    rows = list(rows)
    sent = 0
    for batch in _batched(rows, batch_size):
        with_retry(lambda b=batch: clients.supabase.table(PARENT_TABLE).upsert(b).execute())
        sent += len(batch)
    return sent


def create_parent_row(
    data: dict,
    order: int,
    *,
    owner_guid: Optional[str] = None,
    clients: Optional[Clients] = None,
) -> dict:
    """Build and upsert a single parent row in one call. Returns the row
    dict that was sent."""
    row = create_parent_payload(data, order, owner_guid=owner_guid)
    create_parent_rows([row], clients=clients)
    return row


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def read_parent_row(row_guid: str, *, clients: Optional[Clients] = None) -> Optional[dict]:
    """Fetch one parent row by its ``rowGUID``, or ``None`` if it doesn't
    exist. Mirrors the ``get_rag11_parent`` RPC from
    ``sql/create_sql_tables.sql``, but as a plain REST call."""
    clients = clients or get_clients()
    resp = with_retry(
        lambda: clients.supabase.table(PARENT_TABLE).select("*").eq("rowGUID", row_guid).execute()
    )
    return resp.data[0] if resp.data else None


def read_parent_rows_by_owner(owner_guid: str, *, clients: Optional[Clients] = None) -> List[dict]:
    """Return every parent row belonging to one source (``rowOwnerGUID``),
    ordered by ``orderInList``."""
    clients = clients or get_clients()
    resp = with_retry(
        lambda: clients.supabase.table(PARENT_TABLE)
        .select("*")
        .eq("rowOwnerGUID", owner_guid)
        .order("orderInList")
        .execute()
    )
    return resp.data


def read_all_parent_rows(*, page_size: int = 1000, clients: Optional[Clients] = None) -> List[dict]:
    """Fetch every row in ``rag11_chunks_parent_table`` (paginated
    internally), the same pattern ``stage1_9_eda_verify_all_data.ipynb``
    uses for its integrity check."""
    clients = clients or get_clients()
    rows: List[dict] = []
    start = 0
    while True:
        resp = with_retry(
            lambda s=start: clients.supabase.table(PARENT_TABLE)
            .select("*")
            .range(s, s + page_size - 1)
            .execute()
        )
        page = resp.data
        rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return rows


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def update_parent_rowjson(row_guid: str, patch: dict, *, clients: Optional[Clients] = None) -> dict:
    """Merge ``patch`` into an existing parent row's ``rowJSON`` (an
    ordinary ``UPDATE``, no ``ALTER TABLE`` needed -- same "no stored
    schema change required" pattern as
    ``retrieval.update_rank_value(..., persist=True)``).

    Raises ``ValueError`` if ``row_guid`` doesn't exist. Returns the merged
    ``rowJSON``.
    """
    clients = clients or get_clients()
    current = read_parent_row(row_guid, clients=clients)
    if current is None:
        raise ValueError(f"No parent row with rowGUID={row_guid!r} to update.")
    merged = {**current["rowJSON"], **patch}
    with_retry(
        lambda: clients.supabase.table(PARENT_TABLE)
        .update({"rowJSON": merged})
        .eq("rowGUID", row_guid)
        .execute()
    )
    return merged


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def delete_parent_row(row_guid: str, *, clients: Optional[Clients] = None) -> int:
    """Delete one parent row by ``rowGUID``. Cascades to its child rows via
    the ``rag11_chunks_child_table`` foreign key. Returns the number of rows
    deleted (0 or 1)."""
    clients = clients or get_clients()
    resp = with_retry(
        lambda: clients.supabase.table(PARENT_TABLE).delete().eq("rowGUID", row_guid).execute()
    )
    return len(resp.data)


def delete_parent_rows_by_owner(owner_guid: str, *, clients: Optional[Clients] = None) -> int:
    """Delete every parent row (and, via cascade, every child row) owned by
    one source. Returns the number of parent rows deleted."""
    clients = clients or get_clients()
    resp = with_retry(
        lambda: clients.supabase.table(PARENT_TABLE).delete().eq("rowOwnerGUID", owner_guid).execute()
    )
    return len(resp.data)
