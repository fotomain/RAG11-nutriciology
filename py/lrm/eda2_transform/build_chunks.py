#!/usr/bin/env python3
"""LRM stage 3.4: chunk + embed every uploaded lrm_page_table row into lrm_child_chunk_table. Thin
wrapper -- all the actual logic (token-budget splitting, embedding, upsert) is
reusable_code.eda.chunks.chunk_and_embed().

    python build_chunks.py [--source-key KEY] [--language LANG]

Usage: run after upload.py (see py/run/run2_lrm_upload.command). Needs
sql/create_lrm_tables.sql's lrm_child_chunk_table to already exist -- paste that file into
the Supabase SQL Editor once, first time only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # py/
sys.path.insert(0, str(ROOT))
from reusable_code.eda.chunks import chunk_and_embed  # noqa: E402


def main() -> int:
    source_key = None
    language = None
    args = sys.argv[1:]
    if "--source-key" in args:
        source_key = args[args.index("--source-key") + 1]
    if "--language" in args:
        language = args[args.index("--language") + 1]

    total = chunk_and_embed(source_key, language)
    return 1 if total < 0 else 0


if __name__ == "__main__":
    sys.exit(main())
