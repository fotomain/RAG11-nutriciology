"""LRM stage 3.3: upsert lrm/eda1_extract/output into Supabase (lrm_source_table, lrm_page_table).
Deterministic uuid5 ids make reruns idempotent. Usage: python upload.py

Schema setup/reset is manual, in the Supabase SQL Editor -- paste sql/create_lrm_tables.sql
(or sql/delete_lrm_tables.sql to tear down first). There is no --init/--reset flag here: doing
DDL from this script would need a direct Postgres connection (a second credential beyond the
PUBLIC_SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY this script already uses), which isn't worth the
extra setup for two SQL files you paste in once."""
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # py/lrm/eda3_load/
RAG = ROOT.parent.parent  # py/
sys.path.insert(0, str(RAG))
from reusable_code.clients import make_supabase_client  # noqa: E402

NS = uuid.UUID("6f1c2d9e-3b7a-4c55-9d0e-1a2b3c4d5e6f")
BATCH = 20  # page JSON carries word boxes: keep requests small


def main() -> int:
    if "--init" in sys.argv or "--reset" in sys.argv:
        sql = RAG.parent / "sql"
        print("--init/--reset are no longer automatic here -- schema setup is manual:")
        if "--reset" in sys.argv:
            print(f"  1. paste {sql / 'delete_lrm_tables.sql'} into the Supabase SQL Editor and run it")
            print(f"  2. paste {sql / 'create_lrm_tables.sql'} into the Supabase SQL Editor and run it")
        else:
            print(f"  paste {sql / 'create_lrm_tables.sql'} into the Supabase SQL Editor and run it")
        print("Continuing with the upload itself now (safe to re-run once the schema is in place).")

    sb = make_supabase_client()
    out = RAG / "lrm" / "eda1_extract" / "output"
    # a source only counts once it has at least one recognised page -- an index.json with zero
    # pages (e.g. from a run that failed every page) is not a real source, don't publish a ghost entry
    dirs = sorted(d for d in out.glob("*/*")
                  if (d / "json" / "index.json").exists() and any((d / "json").glob("page_*.json")))

    # sync deletes: drop any Supabase source no longer backed by an output dir on disk (cascades to its pages)
    on_disk = {(d.parent.name, d.name) for d in dirs}
    existing_sources = sb.table("lrm_source_table").select("rowGUID,source_key,language").execute().data
    stale_sources = [r["rowGUID"] for r in existing_sources if (r["language"], r["source_key"]) not in on_disk]
    if stale_sources:
        sb.table("lrm_source_table").delete().in_("rowGUID", stale_sources).execute()
        print(f"removed {len(stale_sources)} stale source(s) no longer in lrm/eda1_extract/output")

    if not dirs:
        print("nothing in lrm/eda1_extract/output -- run run1_lrm_eda.command first")
        return 1
    for order, d in enumerate(dirs):
        lang, key = d.parent.name, d.name
        idx = json.loads((d / "json" / "index.json").read_text())
        pages = [json.loads(f.read_text()) for f in sorted((d / "json").glob("page_*.json"))]
        sid = str(uuid.uuid5(NS, f"source:{key}:{lang}"))
        sb.table("lrm_source_table").upsert({
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
            sb.table("lrm_page_table").upsert(rows[i:i + BATCH], on_conflict="rowGUID").execute()

        # sync deletes: drop any page Supabase has for this source that no longer has a page_*.json on disk
        # (e.g. re-recognised with a smaller --end, or a page file removed)
        existing_pages = (sb.table("lrm_page_table").select("rowGUID,page_number")
                           .eq("source_key", key).eq("language", lang).execute().data)
        stale_pages = [r["rowGUID"] for r in existing_pages if r["page_number"] not in disk_page_numbers]
        if stale_pages:
            sb.table("lrm_page_table").delete().in_("rowGUID", stale_pages).execute()
            print(f"  removed {len(stale_pages)} stale page(s) for {lang}/{key}")
        print(f"uploaded {lang}/{key}: {len(rows)} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
