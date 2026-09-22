"""CRUD operations for ``rag11_chunks_child_table`` (one row per embeddable
chunk + its Voyage embedding -- see ``sql/create_sql_tables.sql``).

Row-level counterpart to what ``stage1_2_eda_load_chunks.ipynb`` does inline
for bulk ingestion, exposed as small, independently callable functions --
for any notebook or script that needs to create, read, update, or delete a
single child row (or a handful of them) without re-running the whole
Stage 1.2 pipeline. See ``crud_chunks_parent.py`` for the parent-row
equivalent (and for the shared ``deterministic_uuid``/``RAG11_UUID_NAMESPACE``
this module reuses).

Every public function name is prefixed ``create_``, ``read_``, ``update_``,
or ``delete_``, naming the CRUD operation it performs.
"""
from typing import Iterable, List, Optional

from .clients import Clients, get_clients
from .crud_chunks_parent import RAG11_UUID_NAMESPACE, deterministic_uuid  # noqa: F401 -- re-exported
from .retry import with_retry

CHILD_TABLE = "rag11_chunks_child_table"


def _batched(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def create_child_payload(
    data: dict,
    order: int,
    embedding: List[float],
    *,
    owner_guid: Optional[str] = None,
) -> dict:
    """Build one ``rag11_chunks_child_table`` row dict from a
    ``child_chunk-parentN-chunkM.json``-shaped payload plus its already-computed
    embedding, without writing it anywhere.

    ``data`` must contain ``"child_id"`` and ``"parent_id"`` (the stable
    business keys ``rowGUID``/``rowParentGUID`` are derived from --
    ``rowParentGUID`` is computed the same way ``create_parent_payload``
    computes a parent's ``rowGUID``, so it always matches an existing
    parent row). ``owner_guid`` is the owning source's
    ``rag11_data_sources.rowGUID``; if omitted, it's read from
    ``data["source_row_guid"]``.
    """
    resolved_owner = owner_guid or data.get("source_row_guid")
    if not resolved_owner:
        raise ValueError(
            "No owner_guid given and data has no 'source_row_guid' -- pass "
            "owner_guid explicitly (the child chunk's rag11_data_sources rowGUID)."
        )
    return {
        "rowGUID": deterministic_uuid(f"child:{data['child_id']}"),
        "rowOwnerGUID": resolved_owner,
        "rowParentGUID": deterministic_uuid(f"parent:{data['parent_id']}"),
        "orderInList": order,
        "rowJSON": data,
        "embedding": embedding,
    }


def create_child_rows(
    rows: Iterable[dict],
    *,
    batch_size: int = 100,
    clients: Optional[Clients] = None,
) -> int:
    """Upsert already-built child row dicts (see ``create_child_payload``)
    into ``rag11_chunks_child_table``, in batches of ``batch_size``. Upsert
    (not plain insert) means calling this again with the same rows is
    always safe.

    Returns the number of rows sent (not necessarily the number changed).
    """
    clients = clients or get_clients()
    rows = list(rows)
    sent = 0
    for batch in _batched(rows, batch_size):
        with_retry(lambda b=batch: clients.supabase.table(CHILD_TABLE).upsert(b).execute())
        sent += len(batch)
    return sent


def create_child_row(
    data: dict,
    order: int,
    embedding: List[float],
    *,
    owner_guid: Optional[str] = None,
    clients: Optional[Clients] = None,
) -> dict:
    """Build and upsert a single child row in one call. Returns the row
    dict that was sent."""
    row = create_child_payload(data, order, embedding, owner_guid=owner_guid)
    create_child_rows([row], clients=clients)
    return row


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def read_child_row(row_guid: str, *, clients: Optional[Clients] = None) -> Optional[dict]:
    """Fetch one child row (including its embedding) by ``rowGUID``, or
    ``None`` if it doesn't exist."""
    clients = clients or get_clients()
    resp = with_retry(
        lambda: clients.supabase.table(CHILD_TABLE).select("*").eq("rowGUID", row_guid).execute()
    )
    return resp.data[0] if resp.data else None


def read_child_rows_by_parent(parent_guid: str, *, clients: Optional[Clients] = None) -> List[dict]:
    """Return every child row belonging to one parent chunk
    (``rowParentGUID``), ordered by ``orderInList``."""
    clients = clients or get_clients()
    resp = with_retry(
        lambda: clients.supabase.table(CHILD_TABLE)
        .select("*")
        .eq("rowParentGUID", parent_guid)
        .order("orderInList")
        .execute()
    )
    return resp.data


def read_child_rows_by_owner(owner_guid: str, *, clients: Optional[Clients] = None) -> List[dict]:
    """Return every child row belonging to one source (``rowOwnerGUID``)."""
    clients = clients or get_clients()
    resp = with_retry(
        lambda: clients.supabase.table(CHILD_TABLE).select("*").eq("rowOwnerGUID", owner_guid).execute()
    )
    return resp.data


def read_all_child_rows(*, page_size: int = 1000, clients: Optional[Clients] = None) -> List[dict]:
    """Fetch every row in ``rag11_chunks_child_table`` (paginated
    internally, including embeddings), the same pattern
    ``stage1_9_eda_verify_all_data.ipynb`` uses for its integrity check."""
    clients = clients or get_clients()
    rows: List[dict] = []
    start = 0
    while True:
        resp = with_retry(
            lambda s=start: clients.supabase.table(CHILD_TABLE)
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


def update_child_rowjson(row_guid: str, patch: dict, *, clients: Optional[Clients] = None) -> dict:
    """Merge ``patch`` into an existing child row's ``rowJSON`` (an ordinary
    ``UPDATE``, no ``ALTER TABLE`` needed -- same pattern
    ``retrieval.update_rank_value(..., persist=True)`` already uses for
    ``manual_rank_score``/``manual_rank_reason``).

    Raises ``ValueError`` if ``row_guid`` doesn't exist. Returns the merged
    ``rowJSON``.
    """
    clients = clients or get_clients()
    current = read_child_row(row_guid, clients=clients)
    if current is None:
        raise ValueError(f"No child row with rowGUID={row_guid!r} to update.")
    merged = {**current["rowJSON"], **patch}
    with_retry(
        lambda: clients.supabase.table(CHILD_TABLE)
        .update({"rowJSON": merged})
        .eq("rowGUID", row_guid)
        .execute()
    )
    return merged


def update_child_embedding(
    row_guid: str, embedding: List[float], *, clients: Optional[Clients] = None
) -> None:
    """Overwrite one child row's ``embedding`` column (e.g. after
    re-embedding its text with a new model) -- a plain column update, not a
    ``rowJSON`` merge, since ``embedding`` lives outside ``rowJSON``."""
    clients = clients or get_clients()
    with_retry(
        lambda: clients.supabase.table(CHILD_TABLE)
        .update({"embedding": embedding})
        .eq("rowGUID", row_guid)
        .execute()
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def delete_child_row(row_guid: str, *, clients: Optional[Clients] = None) -> int:
    """Delete one child row by ``rowGUID``. Returns the number of rows
    deleted (0 or 1)."""
    clients = clients or get_clients()
    resp = with_retry(
        lambda: clients.supabase.table(CHILD_TABLE).delete().eq("rowGUID", row_guid).execute()
    )
    return len(resp.data)


def delete_child_rows_by_parent(parent_guid: str, *, clients: Optional[Clients] = None) -> int:
    """Delete every child row belonging to one parent chunk. Returns the
    number of rows deleted."""
    clients = clients or get_clients()
    resp = with_retry(
        lambda: clients.supabase.table(CHILD_TABLE).delete().eq("rowParentGUID", parent_guid).execute()
    )
    return len(resp.data)


def delete_child_rows_by_owner(owner_guid: str, *, clients: Optional[Clients] = None) -> int:
    """Delete every child row belonging to one source. Returns the number
    of rows deleted."""
    clients = clients or get_clients()
    resp = with_retry(
        lambda: clients.supabase.table(CHILD_TABLE).delete().eq("rowOwnerGUID", owner_guid).execute()
    )
    return len(resp.data)
