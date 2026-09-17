"""Refactors stage2_ask_examples1.ipynb in place to import its retrieval/
generation logic from ./reusable_code/ instead of redefining it inline --
run this script with plain python3 (stdlib json only) from the repo root.
Cell count and every '# Cell #NN' label are preserved exactly.
"""
import json

PATH = "stage2_ask_examples1.ipynb"


def lines(text: str):
    body = text if text.endswith("\n") else text + "\n"
    return body.splitlines(keepends=True)


CELL_02 = """# Cell #02
from reusable_code import init_clients, EMBEDDING_MODEL, GENERATION_MODEL
from reusable_code.env import optional_env

# Client construction (Supabase / Voyage / Anthropic) and env-var loading now
# live in ./reusable_code/clients.py, shared with stage2_ask_examples2_rerank.ipynb
# -- see reusable_code/README.md for the full guide. EMBEDDING_MODEL and
# GENERATION_MODEL are defined there too now (must match
# stage1_2_eda_load_chunks.ipynb's EMBEDDING_MODEL).
clients = init_clients()
supabase = clients.supabase
voyage_client = clients.voyage
anthropic_client = clients.anthropic

print("Clients ready. Supabase project:", optional_env("PUBLIC_SUPABASE_URL"))
"""

CELL_04 = """# Cell #04
from reusable_code import (
    with_retry as _retry,
    MIN_CONTEXT_CHUNKS,
    NUM_CONTEXT_CHUNKS,
    embed_query,
    retrieve_chunks,
    page_numbers_for_chunk,
)

# embed_query() / retrieve_chunks() / page_numbers_for_chunk() now live in
# ./reusable_code/retrieval.py (shared with stage2_ask_examples2_rerank.ipynb).
# They use the `clients` bundle from the cell above by default, so calls
# below are unchanged: retrieve_chunks(question, match_count=...).
"""

CELL_06 = """# Cell #06
from reusable_code import (
    SYSTEM_PROMPT,
    MAX_ANSWER_TOKENS,
    build_context_block,
    extract_short_answer,
    grounding_words,
    ask_question,
)

# build_context_block() / extract_short_answer() / grounding_words() /
# ask_question() now live in ./reusable_code/generation.py (shared with
# stage2_ask_examples2_rerank.ipynb). ask_question() also gained an optional
# `use_rerank=True/False` keyword (default False, matching this notebook's
# original behavior exactly) -- see stage2_ask_examples2_rerank.ipynb for a
# worked example, or reusable_code/README.md for the full guide.
"""

CELL_14 = """# Cell #14
from reusable_code import save_to_github

save_to_github("stage2_ask_examples1.ipynb - answers verified and synced")
"""

INTRO_APPEND = (
    "\n\n**2026-09-17 update:** retrieval/generation logic now lives in "
    "`./reusable_code/` (shared with `stage2_ask_examples2_rerank.ipynb`, which "
    "adds an optional reranking pass on top of this same pipeline) -- see "
    "`reusable_code/README.md`."
)

with open(PATH) as f:
    nb = json.load(f)

cells = nb["cells"]
assert len(cells) == 14, f"expected 14 cells, found {len(cells)} -- aborting, notebook shape changed"

# Cell 0: markdown intro -- append the update note, don't touch anything else.
assert cells[0]["cell_type"] == "markdown"
cells[0]["source"] = cells[0]["source"] + lines(INTRO_APPEND)

# Cell 1: Cell #02 -- client setup
assert cells[1]["cell_type"] == "code" and "".join(cells[1]["source"]).startswith("# Cell #02")
cells[1]["source"] = lines(CELL_02)

# Cell 3: Cell #04 -- retrieval helpers
assert cells[3]["cell_type"] == "code" and "".join(cells[3]["source"]).startswith("# Cell #04")
cells[3]["source"] = lines(CELL_04)

# Cell 5: Cell #06 -- generation helpers + ask_question
assert cells[5]["cell_type"] == "code" and "".join(cells[5]["source"]).startswith("# Cell #06")
cells[5]["source"] = lines(CELL_06)

# Cell 13: Cell #14 -- save_to_github
assert cells[13]["cell_type"] == "code" and "".join(cells[13]["source"]).startswith("# Cell #14")
cells[13]["source"] = lines(CELL_14)

with open(PATH, "w") as f:
    json.dump(nb, f, indent=1)
    f.write("\n")

print("stage2_ask_examples1.ipynb refactored to use reusable_code -- 14 cells preserved.")
