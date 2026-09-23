#!/usr/bin/env python3
"""LRM stage 3.3: upsert lrm/eda1_extract/output into Supabase (lrm_source_table, lrm_page_table).
Thin wrapper -- all the actual logic (upsert, two-way sync of deletes) is
reusable_code.eda.load.upload.sync_to_supabase(). Usage: python upload.py

Schema setup/reset is manual, in the Supabase SQL Editor -- paste sql/create_lrm_tables.sql
(or sql/delete_lrm_tables.sql to tear down first). There is no --init/--reset flag here: doing
DDL from this script would need a direct Postgres connection (a second credential beyond the
PUBLIC_SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY this script already uses), which isn't worth the
extra setup for two SQL files you paste in once."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # py/
sys.path.insert(0, str(ROOT))
from reusable_code.eda.load.upload import sync_to_supabase  # noqa: E402


def main() -> int:
    if "--init" in sys.argv or "--reset" in sys.argv:
        sql = ROOT.parent / "sql"
        print("--init/--reset are no longer automatic here -- schema setup is manual:")
        if "--reset" in sys.argv:
            print(f"  1. paste {sql / 'delete_lrm_tables.sql'} into the Supabase SQL Editor and run it")
            print(f"  2. paste {sql / 'create_lrm_tables.sql'} into the Supabase SQL Editor and run it")
        else:
            print(f"  paste {sql / 'create_lrm_tables.sql'} into the Supabase SQL Editor and run it")
        print("Continuing with the upload itself now (safe to re-run once the schema is in place).")

    output_dir = ROOT / "lrm" / "eda1_extract" / "output"
    return 0 if sync_to_supabase(output_dir) else 1


if __name__ == "__main__":
    sys.exit(main())
