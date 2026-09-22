"""Stage 1.9 -- verify that what is in Supabase matches what is on disk, exactly. Read-only: never writes.

For every single local record (not just row counts) it checks that the row exists, that rowJSON /
rowOwnerGUID / rowParentGUID / orderInList match, that every child has an embedding of the right length,
and that nothing is left in the tables without a local file (orphans). The "expected" rows come from the very
same builders stage 1.2 uses (``common.build_*_row``), so the two can never drift apart.
"""
import html
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ..clients import make_supabase_client
from .common import (CHILD_TABLE, EMBEDDING_DIM, PARENT_TABLE, SOURCES_TABLE, LocalData, banner, build_parent_row,
                     get_paths, load_local_data, retry_db)

SOURCE_COLS = '"rowGUID","rowOwnerGUID","rowParentGUID","orderInList","rowJSON"'
PARENT_COLS = '"rowGUID","rowOwnerGUID","orderInList","rowJSON"'
CHILD_COLS = '"rowGUID","rowOwnerGUID","rowParentGUID","orderInList","rowJSON","embedding"'


# ----------------------------------------------------------------------------------------------- database


def fetch_all_rows(supabase, table_name: str, columns: str, page_size: int = 1000) -> Dict[str, dict]:
    """{rowGUID: row} for every row of a table. ``select()`` is capped per request, so this pages with
    ``.range()`` until a page comes back short (works for a few hundred rows or a few hundred thousand)."""
    rows, start = {}, 0
    while True:
        page = retry_db(lambda: supabase.table(table_name).select(columns).range(start, start + page_size - 1).execute()).data
        for row in page:
            rows[row["rowGUID"]] = row
        if len(page) < page_size:
            return rows
        start += page_size


@dataclass
class DbSnapshot:
    sources: Dict[str, dict]
    parents: Dict[str, dict]
    children: Dict[str, dict]


def fetch_db(supabase, *, verbose: bool = True) -> DbSnapshot:
    snap = []
    for label, table, cols in (("source", SOURCES_TABLE, SOURCE_COLS), ("parent", PARENT_TABLE, PARENT_COLS),
                               ("child (including embeddings)", CHILD_TABLE, CHILD_COLS)):
        if verbose:
            print(f"Fetching all {label} rows from Supabase...")
        rows = fetch_all_rows(supabase, table, cols)
        if verbose:
            print(f"  -> {len(rows)} row(s) in {table}")
        snap.append(rows)
    return DbSnapshot(*snap)


def embedding_length(value) -> int:
    """pgvector comes back over PostgREST as either a JSON list of floats or a "[0.1,0.2,...]" string depending
    on client/library versions; handle both."""
    if value is None:
        return 0
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str):
        return value.count(",") + 1 if value.strip("[]") else 0
    return 0


# ---------------------------------------------------------------------------------------------- comparing


@dataclass
class Report:
    source_ok: int = 0
    source_missing: List[str] = field(default_factory=list)
    source_mismatched: List[str] = field(default_factory=list)
    source_orphaned: List[str] = field(default_factory=list)
    parent_ok: int = 0
    parent_missing: List[Tuple] = field(default_factory=list)
    parent_mismatched: List[Tuple] = field(default_factory=list)
    parent_orphaned: List[str] = field(default_factory=list)
    child_ok: int = 0
    child_missing: List[Tuple] = field(default_factory=list)
    child_mismatched: List[Tuple] = field(default_factory=list)
    child_missing_embedding: List[Tuple] = field(default_factory=list)
    child_orphaned: List[str] = field(default_factory=list)

    @property
    def total_issues(self) -> int:
        return (len(self.source_missing) + len(self.source_mismatched) + len(self.source_orphaned)
                + len(self.parent_missing) + len(self.parent_mismatched) + len(self.parent_orphaned)
                + len(self.child_missing) + len(self.child_mismatched) + len(self.child_missing_embedding)
                + len(self.child_orphaned))

    @property
    def passed(self) -> bool:
        return self.total_issues == 0


def compare_sources(local: LocalData, db: DbSnapshot, report: Report) -> None:
    for local_row in local.source_rows:
        row = db.sources.get(local_row["rowGUID"])
        key = local_row["rowJSON"]["source_key"]
        if row is None:
            report.source_missing.append(key)
        elif (row["rowJSON"] != local_row["rowJSON"] or row["rowOwnerGUID"] != local_row["rowOwnerGUID"]
              or row["rowParentGUID"] is not None or row["orderInList"] != local_row["orderInList"]):
            report.source_mismatched.append(key)
        else:
            report.source_ok += 1
    local_guids = {r["rowGUID"] for r in local.source_rows}
    report.source_orphaned = [g for g in db.sources if g not in local_guids]
    print(f"Source rows -- OK: {report.source_ok}, missing: {len(report.source_missing)}, "
          f"mismatched: {len(report.source_mismatched)}, orphaned in DB: {len(report.source_orphaned)}")
    if report.source_missing:
        print(f"  missing: {report.source_missing}")
    if report.source_mismatched:
        print(f"  mismatched: {report.source_mismatched}")


def _print_first(label_items, kind):
    for label, items in label_items:
        if items:
            print(f"\n  First {min(5, len(items))} {label} {kind} row(s):")
            for source_key, order, ident in items[:5]:
                print(f"    [{source_key} #{order}] {ident}")


def _expected_parents(local: LocalData):
    for k in local.source_keys:
        for order, data in local.parents_by_source[k]:
            yield build_parent_row(k, order, data, local.guid_by_key), k


def compare_parents(local: LocalData, db: DbSnapshot, report: Report) -> None:
    expected = {row["rowGUID"]: (k, row) for row, k in _expected_parents(local)}
    for guid, (k, exp) in expected.items():
        row = db.parents.get(guid)
        ident = (k, exp["orderInList"], exp["rowJSON"].get("parent_id"))
        if row is None:
            report.parent_missing.append(ident)
        elif (row["rowJSON"] != exp["rowJSON"] or row["rowOwnerGUID"] != exp["rowOwnerGUID"]
              or row["orderInList"] != exp["orderInList"]):
            report.parent_mismatched.append(ident)
        else:
            report.parent_ok += 1
    report.parent_orphaned = [g for g in db.parents if g not in expected]
    print(f"Parent rows -- OK: {report.parent_ok}, missing: {len(report.parent_missing)}, "
          f"mismatched: {len(report.parent_mismatched)}, orphaned in DB: {len(report.parent_orphaned)}")
    _print_first([("missing", report.parent_missing), ("mismatched", report.parent_mismatched)], "parent")


def _expected_children(local: LocalData):
    for (k, _order, _data), row in zip(local.child_stubs(), local.child_rows()):
        yield row, k


def compare_children(local: LocalData, db: DbSnapshot, report: Report) -> None:
    expected = {row["rowGUID"]: (k, row) for row, k in _expected_children(local)}
    for guid, (k, exp) in expected.items():
        row = db.children.get(guid)
        ident = (k, exp["orderInList"], exp["rowJSON"].get("child_id"))
        if row is None:
            report.child_missing.append(ident)
        elif not (row["rowJSON"] == exp["rowJSON"] and row["rowOwnerGUID"] == exp["rowOwnerGUID"]
                  and row["rowParentGUID"] == exp["rowParentGUID"] and row["orderInList"] == exp["orderInList"]):
            report.child_mismatched.append(ident)
        elif embedding_length(row.get("embedding")) != EMBEDDING_DIM:
            report.child_missing_embedding.append(ident)
        else:
            report.child_ok += 1
    report.child_orphaned = [g for g in db.children if g not in expected]
    print(f"Child rows -- OK: {report.child_ok}, missing: {len(report.child_missing)}, "
          f"mismatched: {len(report.child_mismatched)}, bad/missing embedding: {len(report.child_missing_embedding)}, "
          f"orphaned in DB: {len(report.child_orphaned)}")
    _print_first([("missing", report.child_missing), ("mismatched", report.child_mismatched),
                  ("with a bad/missing embedding", report.child_missing_embedding)], "child")


# ------------------------------------------------------------------------------------------- summaries


def counts_table_lines(local: LocalData, db: DbSnapshot) -> List[str]:
    """Per-source row counts, local vs. Supabase (difference = local - db; a non-zero row pinpoints the drift)."""
    lp = Counter(k for k in local.source_keys for _ in local.parents_by_source[k])
    lc = Counter(k for k, _o, _d in local.child_stubs())
    dp = Counter(r["rowJSON"].get("source_key", r["rowOwnerGUID"]) for r in db.parents.values())
    dc = Counter(r["rowJSON"].get("source_key", r["rowOwnerGUID"]) for r in db.children.values())
    lines = [f"{'source':<10} {'local parents':>14} {'db parents':>11} {'difference_parents':>19} "
             f"{'local children':>15} {'db children':>12} {'difference_children':>20}"]
    for k in local.source_keys:
        dpar, dchi = lp[k] - dp[k], lc[k] - dc[k]
        flag = "" if (dpar == 0 and dchi == 0) else "  <-- mismatch"
        lines.append(f"{k:<10} {lp[k]:>14} {dp[k]:>11} {dpar:>19} {lc[k]:>15} {dc[k]:>12} {dchi:>20}{flag}")
    return lines


def counts_table_html(lines: List[str]) -> str:
    """The table in its own horizontally scrollable box (it is wider than a notebook output pane)."""
    return ('<div style="overflow-x:auto; max-width:100%; border:1px solid #8888; padding:4px 0;">'
            f'<pre style="margin:0; font-family:monospace; white-space:pre; padding:0 8px;">'
            f'{html.escape(chr(10).join(lines))}</pre></div>')


def smoke_test(supabase, db: DbSnapshot) -> None:
    """Confirms the match_rag11_child_chunks RPC returns results end to end, querying with a stored embedding."""
    sample = next(iter(db.children.values()), None)
    if sample is None:
        print("No child rows in the table yet -- nothing to smoke-test.")
        return
    emb = sample["embedding"]
    if isinstance(emb, str):  # PostgREST may return the vector as a "[...]" string
        emb = [float(x) for x in emb.strip("[]").split(",")]
    resp = retry_db(lambda: supabase.rpc("match_rag11_child_chunks", {"query_embedding": emb, "match_count": 3}).execute())
    print("Smoke-test match_rag11_child_chunks (querying with one child's own embedding):")
    for row in resp.data:
        preview = row["rowJSON"]["text"][:80].replace("\n", " ")
        print(f"  [{row['rowJSON'].get('source_key', row['rowOwnerGUID'])} #{row['orderInList']}] "
              f"dist={row['cosine_distance']:.4f}  {preview}...")


def print_verdict(report: Report) -> None:
    if report.passed:
        print("PASS -- every local source/chunk file matches its row in Supabase exactly, and every child row has "
              "a valid embedding. No orphaned rows either.")
        return
    print(f"FAIL -- {report.total_issues} issue(s) found across the checks above.")
    if report.source_orphaned or report.parent_orphaned or report.child_orphaned:
        print(f"  {len(report.source_orphaned)} orphaned source row(s) + {len(report.parent_orphaned)} orphaned parent "
              f"row(s) + {len(report.child_orphaned)} orphaned child row(s) in Supabase have no matching local file "
              f"-- likely leftovers from before a source/section-count change. Re-run stage 1.2 with orphan pruning "
              f"(--prune-orphans / PRUNE_ORPHANS = True), or see sql/delete_chunks_data.sql.")
    if report.child_missing or report.parent_missing or report.source_missing:
        print("  Some local chunks never made it into Supabase -- re-run stage 1.2 (its checkpoint skips what "
              "already succeeded).")
    if report.child_mismatched or report.parent_mismatched or report.source_mismatched:
        print("  Some rows differ from their local file -- re-run stage 1.2 (it re-sends changed rows).")


# ------------------------------------------------------------------------------------------- everything


def run_stage1_9(root=None, *, supabase=None) -> Report:
    """The whole of stage 1.9."""
    banner("Stage 1.9 -- verify local files against Supabase")
    supabase = supabase or make_supabase_client()
    local = load_local_data(get_paths(root))
    print(f"\nExpected from local files: {local.counts()}")
    db = fetch_db(supabase)
    report = Report()
    compare_sources(local, db, report)
    compare_parents(local, db, report)
    compare_children(local, db, report)
    print()
    print("\n".join(counts_table_lines(local, db)))
    print()
    smoke_test(supabase, db)
    print()
    print_verdict(report)
    return report
