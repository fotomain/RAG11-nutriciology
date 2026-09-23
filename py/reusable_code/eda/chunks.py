"""LRM stage 3.4 engine: chunk + embed every uploaded lrm_page_table row into lrm_child_chunk_table.
Deterministic uuid5 ids make reruns idempotent. Reads from Supabase (not local disk) --
lrm_page_table is already the single source of truth once upload.sync_to_supabase() has run.

Thin CLI wrapper: py/lrm/eda2_transform/build_chunks.py (calls chunk_and_embed() below).
Needs sql/create_lrm_tables.sql's lrm_child_chunk_table to already exist -- paste that file into
the Supabase SQL Editor once, first time only.
"""
from __future__ import annotations

import uuid

import tiktoken

from ..clients import EMBEDDING_MODEL, make_supabase_client, make_voyage_client

# Same namespace upload.py uses for lrm_source_table/lrm_page_table ids -- the "chunk:" prefix below
# keeps chunk ids distinct from "source:"/"page:" ids even though the namespace is shared.
NS = uuid.UUID("6f1c2d9e-3b7a-4c55-9d0e-1a2b3c4d5e6f")

# A page's whole text becomes ONE chunk as long as it fits this budget; only a page that
# runs long (rare -- most scanned book pages are well under this) splits into more than
# one chunk, on block boundaries so a chunk never cuts a sentence/block in half.
CHUNK_TOKEN_BUDGET = 500
BATCH = 20  # Voyage embed() calls: keep requests small, same as upload.py's page-upload BATCH

_ENC = tiktoken.get_encoding("cl100k_base")


def _token_count(text: str) -> int:
    return len(_ENC.encode(text))


def _split_by_blocks(blocks: list[dict], budget: int) -> list[str]:
    """Group blocks (already reading_order-sorted) into token-budget-sized chunks,
    never splitting a block across two chunks."""
    groups, current, current_tokens = [], [], 0
    for b in blocks:
        text = b.get("text", "")
        if not text:
            continue
        t = _token_count(text)
        if current and current_tokens + t > budget:
            groups.append(current)
            current, current_tokens = [], 0
        current.append(text)
        current_tokens += t
    if current:
        groups.append(current)
    return ["\n".join(g) for g in groups] or [""]


def chunks_for_page(page_json: dict) -> list[str]:
    text = page_json.get("text", "")
    if _token_count(text) <= CHUNK_TOKEN_BUDGET:
        return [text]
    blocks = sorted(page_json.get("blocks", []), key=lambda b: b.get("reading_order", 0))
    return _split_by_blocks(blocks, CHUNK_TOKEN_BUDGET)


def chunk_and_embed(source_key: str | None = None, language: str | None = None) -> int:
    """Chunk + embed every lrm_page_table row matching source_key/language (all rows if both are
    None) into lrm_child_chunk_table. Returns the total number of chunks written, or -1 if no
    lrm_page_table rows matched at all (a page matching but producing zero chunks still returns 0)."""
    sb = make_supabase_client()
    voyage = make_voyage_client()

    q = sb.table("lrm_page_table").select('"rowGUID","rowOwnerGUID",source_key,language,page_number,"rowJSON"')
    if source_key:
        q = q.eq("source_key", source_key)
    if language:
        q = q.eq("language", language)
    pages = q.order("source_key").order("language").order("page_number").execute().data

    if not pages:
        print("no lrm_page_table rows match -- run upload.py first")
        return -1

    total_chunks = 0
    for page in pages:
        texts = chunks_for_page(page["rowJSON"])
        if not any(t.strip() for t in texts):
            continue

        embeddings = []
        for i in range(0, len(texts), BATCH):
            resp = voyage.embed(texts=texts[i:i + BATCH], model=EMBEDDING_MODEL, input_type="document")
            embeddings.extend(resp.embeddings)

        # delete this page's existing chunks first, so a rerun with a different split
        # count (page text changed, or CHUNK_TOKEN_BUDGET changed) never leaves stale rows
        sb.table("lrm_child_chunk_table").delete().eq("rowParentGUID", page["rowGUID"]).execute()

        rows = [{
            "rowGUID": str(uuid.uuid5(NS, f"chunk:{page['source_key']}:{page['language']}:{page['page_number']}:{i}")),
            "rowOwnerGUID": page["rowOwnerGUID"],
            "rowParentGUID": page["rowGUID"],
            "orderInList": i,
            "rowJSON": {
                "source_key": page["source_key"],
                "language": page["language"],
                "page_number": page["page_number"],
                "text": text,
            },
            "embedding": embedding,
        } for i, (text, embedding) in enumerate(zip(texts, embeddings))]

        sb.table("lrm_child_chunk_table").upsert(rows, on_conflict="rowGUID").execute()
        total_chunks += len(rows)
        print(f"chunked {page['language']}/{page['source_key']} page {page['page_number']}: {len(rows)} chunk(s)")

    print(f"done: {total_chunks} chunk(s) across {len(pages)} page(s)")
    return total_chunks
