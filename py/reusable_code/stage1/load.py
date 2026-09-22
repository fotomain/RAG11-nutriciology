"""Stage 1.2 -- load the chunks written by stage 1.1 into Supabase.

    sources -> parents -> children (FK order); child chunks are embedded with Voyage first

Idempotent and resumable: every row id is a deterministic uuid5, rows are upserted, and a checkpoint records
``rowGUID -> content fingerprint`` of every row already loaded, so a re-run only embeds and sends rows that are
new or CHANGED (a guid-only checkpoint would silently skip changed rows, and stage 1.9 would report them as
mismatched). An older checkpoint that is a plain list of ids means "contents unknown": every row is re-upserted
once. Rows in Supabase with no local file (orphans) are never touched by an upsert; ``prune_orphans()`` lists
them and deletes them only on request.

If you truncate the tables (sql/delete_chunks_data.sql), also delete eda_output/_checkpoints/.
"""
import concurrent.futures as cf
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from tqdm.auto import tqdm

from ..clients import EMBEDDING_MODEL, make_supabase_client, make_voyage_client
from .common import (CHILD_TABLE, PARENT_TABLE, SOURCES_TABLE, STATEMENT_TIMEOUT_CODE, LocalData, Paths, banner, build_child_row,
                     deterministic_uuid, get_paths, load_local_data, report_open_file_limit, retry_db, row_hash,
                     strip_bad_unicode)

VOYAGE_BATCH_SIZE = 64      # texts per embed() call (well under Voyage's per-request cap)
VOYAGE_MAX_WORKERS = 4      # concurrent in-flight embedding requests
SUPABASE_INSERT_BATCH_SIZE = 100   # rows per upsert() call
# Sequential on purpose: [Errno 35] Resource temporarily unavailable shows up under concurrent upserts on macOS
# when the open-file limit is low. Raise to 2-3 once `ulimit -n` reads >= 2048.
SUPABASE_MAX_WORKERS = 1
SUPABASE_SUBMIT_STAGGER_S = 0.3    # delay between launching each batch
SPLIT_MIN_ROWS = 10                # on a statement timeout, halve the batch until it is this small


@dataclass
class LoaderContext:
    supabase: object
    voyage: object
    paths: Paths
    insert_batch_size: int = SUPABASE_INSERT_BATCH_SIZE
    max_workers: int = SUPABASE_MAX_WORKERS
    stagger_s: float = SUPABASE_SUBMIT_STAGGER_S
    voyage_batch_size: int = VOYAGE_BATCH_SIZE
    voyage_workers: int = VOYAGE_MAX_WORKERS

    @classmethod
    def create(cls, root=None) -> "LoaderContext":
        """Clients from .env (Supabase + Voyage only: this stage needs no Anthropic key)."""
        paths = get_paths(root)
        paths.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        report_open_file_limit()
        ctx = cls(supabase=make_supabase_client(), voyage=make_voyage_client(), paths=paths)
        print("Clients ready (Supabase + Voyage).")
        return ctx


def batched(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


# ---------------------------------------------------------------------------------------------- embeddings


def embed_texts(ctx: LoaderContext, texts: List[str], input_type: str = "document") -> List[List[float]]:
    """Embed ``texts`` with Voyage in parallel batches, preserving input order."""
    batches = list(batched(texts, ctx.voyage_batch_size))

    def embed_one(batch):
        return retry_db(ctx.voyage.embed, texts=batch, model=EMBEDDING_MODEL, input_type=input_type).embeddings

    results: List[Optional[list]] = [None] * len(batches)
    with cf.ThreadPoolExecutor(max_workers=ctx.voyage_workers) as pool:
        future_to_idx = {pool.submit(embed_one, b): i for i, b in enumerate(batches)}
        with tqdm(total=len(batches), desc="Embedding batches", unit="batch") as bar:
            for future in cf.as_completed(future_to_idx):
                results[future_to_idx[future]] = future.result()
                bar.update(1)
    return [e for batch in results for e in batch]


# ---------------------------------------------------------------------------------------------- checkpoint


def checkpoint_path(paths: Paths, table_name: str):
    return paths.checkpoint_dir / f"{table_name}_upserted_row_guids.json"


def load_checkpoint(paths: Paths, table_name: str) -> Dict[str, Optional[str]]:
    """{rowGUID: content fingerprint}; a legacy list of ids loads as {rowGUID: None} (never equals a fingerprint)."""
    p = checkpoint_path(paths, table_name)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {g: None for g in data} if isinstance(data, list) else data


def save_checkpoint(paths: Paths, table_name: str, done: dict) -> None:
    paths.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path(paths, table_name).write_text(json.dumps(done, sort_keys=True), encoding="utf-8")


def is_pending(row: dict, done: dict) -> bool:
    return done.get(row["rowGUID"]) != row_hash(row)


# ---------------------------------------------------------------------------------------------- upserting


def send_rows(ctx: LoaderContext, table_name: str, rows: List[dict]) -> None:
    """Upsert one batch. A Postgres statement timeout (a big batch of vector rows into an HNSW-indexed table gets
    slower as the index grows) is answered by splitting the batch in half rather than retrying the same size."""
    clean = [strip_bad_unicode(r) for r in rows]
    can_split = len(rows) > SPLIT_MIN_ROWS
    try:
        retry_db(lambda: ctx.supabase.table(table_name).upsert(clean).execute(),
                 fail_fast=(STATEMENT_TIMEOUT_CODE,) if can_split else ())
    except Exception as e:  # noqa: BLE001
        if can_split and getattr(e, "code", None) == STATEMENT_TIMEOUT_CODE:
            mid = len(rows) // 2
            print(f"  [split] statement timeout on {len(rows)} rows -> sending {mid} + {len(rows) - mid}")
            send_rows(ctx, table_name, rows[:mid])
            send_rows(ctx, table_name, rows[mid:])
            return
        raise


def upsert_batches(ctx: LoaderContext, table_name: str, rows: List[dict]) -> int:
    """Upsert the rows whose content fingerprint changed since the last successful load; returns how many were sent."""
    done = load_checkpoint(ctx.paths, table_name)
    hashes = {r["rowGUID"]: row_hash(r) for r in rows}
    remaining = [r for r in rows if done.get(r["rowGUID"]) != hashes[r["rowGUID"]]]
    if len(rows) - len(remaining):
        print(f"  [{table_name}] skipping {len(rows) - len(remaining)} row(s) already upserted with identical content")

    batches = list(batched(remaining, ctx.insert_batch_size))
    inserted = 0

    def upsert_one(batch):
        send_rows(ctx, table_name, batch)
        return [r["rowGUID"] for r in batch]

    with cf.ThreadPoolExecutor(max_workers=ctx.max_workers) as pool:
        futures = []
        for b in batches:
            futures.append(pool.submit(upsert_one, b))
            time.sleep(ctx.stagger_s)
        with tqdm(total=len(batches), desc=f"Upserting {table_name}", unit="batch") as bar:
            for future in cf.as_completed(futures):
                guids = future.result()
                inserted += len(guids)
                done.update({g: hashes[g] for g in guids})
                # Checkpoint after every batch, from this single main thread, so a crash loses at most in-flight batches.
                save_checkpoint(ctx.paths, table_name, done)
                bar.update(1)
    return inserted


def _timed_upsert(ctx, table_name, rows, label) -> int:
    print(f"Upserting {len(rows)} {label} row(s) into {table_name}...")
    t0 = time.monotonic()
    n = upsert_batches(ctx, table_name, rows)
    dt = time.monotonic() - t0
    print(f"  -> {n} {label} row(s) upserted in {dt:.1f}s" + (f" ({n / dt:.1f} rows/s)." if n and dt > 0 else "."))
    return n


def upsert_sources(ctx: LoaderContext, local: LocalData) -> int:
    """Sources first: parent and child rows carry a foreign key onto rag11_data_sources.rowGUID."""
    return _timed_upsert(ctx, SOURCES_TABLE, local.source_rows, "source")


def upsert_parents(ctx: LoaderContext, local: LocalData) -> int:
    """Parents before children: the child table's rowParentGUID is a foreign key onto the parent table."""
    return _timed_upsert(ctx, PARENT_TABLE, local.parent_rows(), "parent")


def upsert_children(ctx: LoaderContext, local: LocalData) -> int:
    """Embed only the children that are new or changed (one combined sweep keeps every Voyage batch full), then upsert them."""
    stubs = local.child_stubs()
    done = load_checkpoint(ctx.paths, CHILD_TABLE)
    pending = [(k, o, d) for k, o, d in stubs if is_pending(build_child_row(k, o, d, local.guid_by_key), done)]
    print(f"{len(pending)} of {len(stubs)} child chunk(s) are new or changed -> embedding only those "
          f"(batch size {ctx.voyage_batch_size}, {ctx.voyage_workers} parallel workers)...")

    embeddings: list = []
    if pending:
        t0 = time.monotonic()
        embeddings = embed_texts(ctx, [d["text"] for _k, _o, d in pending])
        dt = time.monotonic() - t0
        print(f"  -> embedded {len(embeddings)} chunks in {dt:.1f}s ({len(embeddings) / dt if dt > 0 else float('inf'):.1f} chunks/s).")
    if len(embeddings) != len(pending):
        raise RuntimeError(f"embedding count mismatch: {len(embeddings)} embeddings for {len(pending)} chunks")

    rows = [build_child_row(k, o, d, local.guid_by_key, emb) for (k, o, d), emb in zip(pending, embeddings)]
    return _timed_upsert(ctx, CHILD_TABLE, rows, "child")


# ------------------------------------------------------------------------------------------------ orphans


def fetch_guid_owner(ctx: LoaderContext, table_name: str, page_size: int = 1000) -> Dict[str, str]:
    """{rowGUID: rowOwnerGUID} for every row of a table (paginated)."""
    out, start = {}, 0
    while True:
        page = retry_db(lambda: ctx.supabase.table(table_name).select('"rowGUID","rowOwnerGUID"')
                        .range(start, start + page_size - 1).execute()).data
        out.update({r["rowGUID"]: r["rowOwnerGUID"] for r in page})
        if len(page) < page_size:
            return out
        start += page_size


def prune_orphans(ctx: LoaderContext, local: LocalData, *, prune: bool = False) -> int:
    """List (and, with ``prune=True``, delete) parent/child rows in Supabase that have no local file.

    Safety rails: only rows owned by a source present in the local output are considered (loading a partial local
    folder can't wipe other sources), source rows are never deleted here, and nothing is deleted unless ``prune``.
    Returns the number of orphans found.
    """
    owners = {r["rowGUID"] for r in local.source_rows}
    local_guids = {
        CHILD_TABLE: {deterministic_uuid(f"child:{d['child_id']}") for _k, _o, d in local.child_stubs()},
        PARENT_TABLE: {r["rowGUID"] for r in local.parent_rows()},
    }
    total = 0
    for table_name in (CHILD_TABLE, PARENT_TABLE):
        in_db = fetch_guid_owner(ctx, table_name)
        orphans = sorted(g for g, owner in in_db.items() if g not in local_guids[table_name] and owner in owners)
        total += len(orphans)
        print(f"{table_name}: {len(orphans)} orphaned row(s) in Supabase (of {len(in_db)})")
        if orphans and prune:
            for batch in batched(orphans, 100):
                retry_db(lambda b=batch: ctx.supabase.table(table_name).delete().in_("rowGUID", b).execute())
            gone = set(orphans)
            save_checkpoint(ctx.paths, table_name,
                            {g: h for g, h in load_checkpoint(ctx.paths, table_name).items() if g not in gone})
            print(f"  -> deleted {len(orphans)}")
    if total and not prune:
        print("\nRe-run with pruning enabled (PRUNE_ORPHANS = True / --prune-orphans) to delete them.")
    return total


# ------------------------------------------------------------------------------------------- everything


@dataclass
class Result:
    n_sources: int
    n_parents: int
    n_children: int
    n_orphans: int


def run_stage1_2(root=None, *, prune: bool = False, ctx: Optional[LoaderContext] = None) -> Result:
    """The whole of stage 1.2."""
    banner("Stage 1.2 -- embed & load into Supabase")
    ctx = ctx or LoaderContext.create(root)
    local = load_local_data(ctx.paths)
    n_s = upsert_sources(ctx, local)
    n_p = upsert_parents(ctx, local)
    n_c = upsert_children(ctx, local)
    n_o = prune_orphans(ctx, local, prune=prune)
    print("\nStage 1.2 ingestion complete.")
    return Result(n_s, n_p, n_c, n_o)
