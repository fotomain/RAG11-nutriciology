"""LRM stage 3.3: upsert lrm/data/output into Supabase (lrm_sources, lrm_pages).
Deterministic uuid5 ids make reruns idempotent. Usage: python upload.py [--init] [--reset]"""
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # py/lrm/upload/
RAG = ROOT.parent.parent  # py/
sys.path.insert(0, str(RAG))
from reusable_code.clients import make_supabase_client  # noqa: E402

NS = uuid.UUID("6f1c2d9e-3b7a-4c55-9d0e-1a2b3c4d5e6f")
BATCH = 20  # page JSON carries word boxes: keep requests small


def run_sql(path: Path) -> None:
    import os
    import psycopg
    from reusable_code.env import require_env
    with psycopg.connect(require_env("LRM_DB_URL"), autocommit=True) as c:
        c.execute(path.read_text())


def main() -> int:
    init = RAG / "lrm" / "init"
    if "--reset" in sys.argv:
        run_sql(init / "delete_lrm_tables.sql")
    if "--init" in sys.argv or "--reset" in sys.argv:
        run_sql(init / "create_lrm_tables.sql")
    sb = make_supabase_client()
    out = RAG / "lrm" / "data" / "output"
    # a source only counts once it has at least one recognised page -- an index.json with zero
    # pages (e.g. from a run that failed every page) is not a real source, don't publish a ghost entry
    dirs = sorted(d for d in out.glob("*/*")
                  if (d / "json" / "index.json").exists() and any((d / "json").glob("page_*.json")))

    # sync deletes: drop any Supabase source no longer backed by an output dir on disk (cascades to its pages)
    on_disk = {(d.parent.name, d.name) for d in dirs}
    existing_sources = sb.table("lrm_sources").select("rowGUID,source_key,language").execute().data
    stale_sources = [r["rowGUID"] for r in existing_sources if (r["language"], r["source_key"]) not in on_disk]
    if stale_sources:
        sb.table("lrm_sources").delete().in_("rowGUID", stale_sources).execute()
        print(f"removed {len(stale_sources)} stale source(s) no longer in lrm/data/output")

    if not dirs:
        print("nothing in lrm/data/output -- run run1_lrm_eda.command first")
        return 1
    for order, d in enumerate(dirs):
        lang, key = d.parent.name, d.name
        idx = json.loads((d / "json" / "index.json").read_text())
        pages = [json.loads(f.read_text()) for f in sorted((d / "json").glob("page_*.json"))]
        sid = str(uuid.uuid5(NS, f"source:{key}:{lang}"))
        sb.table("lrm_sources").upsert({
            "rowGUID": sid, "rowOwnerGUID": sid, "rowParentGUID": None, "orderInList": order,
            "rowJSON": {"source_key": key, "language": lang, "title": key.replace("_", " "),
                        "page_count": idx.get("total_pages", len(pages)), "recognised_pages": len(pages)},
        }, on_conflict="rowGUID").execute()
        rows = []
        disk_page_numbers = set()
        for pg in pages:
            n = pg["page"]
            disk_page_numbers.add(n)
            pg["source_key"], pg["language"], pg["page_number"] = key, lang, n
            pg["text"] = "\n".join(b["text"] for b in pg["blocks"] if b["text"])
            rows.append({"rowGUID": str(uuid.uuid5(NS, f"page:{key}:{lang}:{n}")), "rowOwnerGUID": sid,
                         "rowParentGUID": sid, "orderInList": n, "rowJSON": pg})
        for i in range(0, len(rows), BATCH):
            sb.table("lrm_pages").upsert(rows[i:i + BATCH], on_conflict="rowGUID").execute()

        # sync deletes: drop any page Supabase has for this source that no longer has a page_*.json on disk
        # (e.g. re-recognised with a smaller --end, or a page file removed)
        existing_pages = (sb.table("lrm_pages").select("rowGUID,page_number")
                           .eq("source_key", key).eq("language", lang).execute().data)
        stale_pages = [r["rowGUID"] for r in existing_pages if r["page_number"] not in disk_page_numbers]
        if stale_pages:
            sb.table("lrm_pages").delete().in_("rowGUID", stale_pages).execute()
            print(f"  removed {len(stale_pages)} stale page(s) for {lang}/{key}")
        print(f"uploaded {lang}/{key}: {len(rows)} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
