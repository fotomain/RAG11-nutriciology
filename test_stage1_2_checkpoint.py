"""Offline test of stage1_2's content-aware checkpoint (cell #12), executed straight from the
notebook source against a fake Supabase client. Run: .venv/bin/python test_stage1_2_checkpoint.py"""
import concurrent.futures as cf
import json
import random
import sys
import tempfile
import time
from pathlib import Path

failures = []


def check(name, cond):
    print(("[PASS] " if cond else "[FAIL] ") + name)
    if not cond:
        failures.append(name)


class _Table:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def upsert(self, rows):
        self.rows = rows
        return self

    def execute(self):
        for r in self.rows:
            self.db.setdefault(self.name, {})[r["rowGUID"]] = r
        return self


class _FakeSupabase:
    def __init__(self):
        self.db = {}

    def table(self, name):
        return _Table(self.db, name)


class _Tqdm:
    def __init__(self, **kw): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def update(self, n): pass


nb = json.load(open("stage1_2_eda_load_chunks.ipynb", encoding="utf-8"))
cell = next(c for c in nb["cells"] if c["cell_type"] == "code" and "def _upsert_batches" in "".join(c["source"]))
supabase = _FakeSupabase()
tmp = Path(tempfile.mkdtemp())
env = dict(
    json=json, Path=Path, cf=cf, time=time, random=random, tqdm=_Tqdm, CHECKPOINT_DIR=tmp, supabase=supabase,
    _retry=lambda fn, *a, **k: fn(*a, **k),
    _batched=lambda seq, size: [seq[i:i + size] for i in range(0, len(seq), size)],
)
exec("".join(cell["source"]).replace("SUPABASE_SUBMIT_STAGGER_S = 0.3", "SUPABASE_SUBMIT_STAGGER_S = 0"), env)
up = env["_upsert_batches"]

rows = [{"rowGUID": f"g{i}", "rowJSON": {"text": f"t{i}"}, "embedding": [0.1]} for i in range(5)]
check("first load upserts everything", up("t", rows) == 5)
check("unchanged rows are skipped", up("t", rows) == 0)
rows[2]["rowJSON"]["text"] = "CHANGED"
check("a changed row is re-upserted (and only it)", up("t", rows) == 1 and supabase.db["t"]["g2"]["rowJSON"]["text"] == "CHANGED")
rows[3]["embedding"] = [9.9]
check("embedding-only difference does not count as a change", up("t", rows) == 0)
rows[1]["rowJSON"]["text"] = "bad\x00nul"
check("NUL bytes are fingerprinted after stripping (stable across runs)", up("t", rows) == 1 and up("t", rows) == 0)

(tmp / "legacy_upserted_row_guids.json").write_text(json.dumps(["g0", "g1"]))
check("legacy list checkpoint: rows re-upserted once", up("legacy", rows[:2]) == 2)
check("legacy list checkpoint: then stable", up("legacy", rows[:2]) == 0)

print("\nAll checks passed." if not failures else f"\n{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
