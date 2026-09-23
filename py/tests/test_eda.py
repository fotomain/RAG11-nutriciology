"""Offline tests for reusable_code.eda -- no network access or .env values required beyond what
python-dotenv loads from py/.env at import time (GOOGLE_AI_API_KEY only needs to exist, never
called here). Run: .venv/bin/python test_eda.py

Covers the pure/algorithmic pieces (page-window resolution, box normalisation, page-doc assembly,
chunk splitting, language detection, link_book()'s on-disk pass) and a disk<->Supabase sync test
against a fully faked Supabase client. Nothing here calls Gemini/Bedrock/Voyage.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, ".")

from reusable_code.eda import recognize as rc  # noqa: E402
from reusable_code.eda.load import upload as up  # noqa: E402
from reusable_code.eda.chunks import _split_by_blocks, chunks_for_page  # noqa: E402
from reusable_code.eda.download import detect  # noqa: E402

FAILURES = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


# ---------- page-window resolution (START_PAGE_NUMBER / MAX_NUMBER_OF_PAGES_TO_USE) ----------
# Regression coverage for the bug where MAX_NUMBER_OF_PAGES_TO_USE was treated as an absolute end
# page instead of a page COUNT from start -- START_PAGE_NUMBER=303 + MAX_NUMBER_OF_PAGES_TO_USE=3
# used to resolve to an empty range (end=3 < start=303).

def with_env(**kv):
    """Context manager: set env vars, restore the previous values on exit."""
    class _Ctx:
        def __enter__(self):
            self.prev = {k: os.environ.get(k) for k in kv}
            os.environ.update({k: v for k, v in kv.items() if v is not None})
            for k, v in kv.items():
                if v is None:
                    os.environ.pop(k, None)
            return self

        def __exit__(self, *a):
            for k, v in self.prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return _Ctx()


with with_env(START_PAGE_NUMBER="303", MAX_NUMBER_OF_PAGES_TO_USE="3"):
    check("start_page() reads START_PAGE_NUMBER", rc.start_page() == 303)
    check("resolve_end(303, None) is a 3-page COUNT from start (305), not the literal 3",
          rc.resolve_end(303, None) == 305)

with with_env(START_PAGE_NUMBER=None, MAX_NUMBER_OF_PAGES_TO_USE=None):
    check("start_page() defaults to 1 when unset", rc.start_page() == 1)
    check("resolve_end(1, None) defaults to page 100 (MAX_NUMBER_OF_PAGES_TO_USE default)", rc.resolve_end(1, None) == 100)

with with_env(MAX_NUMBER_OF_PAGES_TO_USE="NONE"):
    check("max_pages() returns None for NONE (whole book)", rc.max_pages() is None)
    check("resolve_end(303, None) is None (no limit) when MAX_NUMBER_OF_PAGES_TO_USE=NONE", rc.resolve_end(303, None) is None)

check("resolve_end() an explicit --end always wins over MAX_NUMBER_OF_PAGES_TO_USE",
      rc.resolve_end(303, 400) == 400)


# ---------- slug() / norm_box() / clamp() / fold() ----------

check("slug() lowercases and collapses punctuation/spaces to underscores",
      rc.slug("Yogasutra.janvier. 2020.pdf, éd. 2021") == "yogasutra_janvier_2020_pdf_d_2021")
check("slug() of an empty/all-punctuation name falls back to 'source'", rc.slug("...") == "source")

check("clamp() leaves in-range values alone", rc.clamp(500) == 500)
check("clamp() floors below 0", rc.clamp(-10) == 0)
check("clamp() ceils above 1000", rc.clamp(1500) == 1000)

check("norm_box() converts 0-1000 ints to 0..1 fractions",
      rc.norm_box([0, 0, 500, 1000]) == {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.5})
check("norm_box() swaps an inverted [ymax<ymin] pair instead of producing a negative height",
      rc.norm_box([500, 0, 100, 1000])["h"] == 0.4)
check("norm_box() rejects a malformed (non-4-element) box", rc.norm_box([1, 2, 3]) is None)
check("norm_box() rejects a non-list box", rc.norm_box("nope") is None)

check("fold() strips accents and lowercases", rc.fold("Café") == "cafe")
check("fold() drops punctuation, keeps alphanumerics", rc.fold("l'ashram, 1.2!") == "lashram12")


# ---------- build_page() ----------

def _raw_page():
    return {
        "printed_page_number": "12",
        "blocks": [
            {"block_id": "b1", "type": "heading", "box": [0, 0, 100, 1000],
             "words": [{"t": "Chapitre", "box": [0, 0, 50, 200], "lang": "src", "style": "normal"},
                       {"t": "I", "box": [0, 210, 50, 250], "lang": "src", "style": "normal"}]},
            {"block_id": "b2", "type": "footnote", "parent_block_id": "b1", "footnote_marker": "1",
             "box": [900, 0, 950, 500],
             "words": [{"t": "note.", "box": [900, 0, 950, 100], "lang": "src", "style": "normal"}]},
        ],
    }


rc.LANG, rc.KEY = "fr", "test_book"
_page = rc.build_page(_raw_page(), 12, (2000, 3000), "gemini-3.6-flash", "book.pdf")

check("build_page() ids blocks p<page>_b<n>", _page["blocks"][0]["id"] == "p0012_b001")
check("build_page() joins word text with single spaces", _page["blocks"][0]["text"] == "Chapitre I")
check("build_page() computes char_start/char_end per word",
      [w["char_end"] for w in _page["blocks"][0]["words"]] == [8, 10])
check("build_page() resolves parent_block_id from the local footnote->heading link",
      _page["blocks"][1]["parent_block_id"] == _page["blocks"][0]["id"])
check("build_page() drops the internal _parent_local scratch key", "_parent_local" not in _page["blocks"][0])
check("build_page() carries printed_page_number/source/model through", (
    _page["printed_page_number"], _page["source"], _page["model"]) == ("12", "book.pdf", "gemini-3.6-flash"))
check("build_page() a word with lang='src' is relabelled to the page's actual language",
      _page["blocks"][0]["words"][0]["lang"] == "fr")
check("build_page() image path is <lang>/<key>/pages/page_NNNN.png",
      _page["image"] == "fr/test_book/pages/page_0012.png")

_raw_bad_word = {"printed_page_number": "", "blocks": [{"block_id": "b1", "type": "paragraph", "box": [0, 0, 10, 10],
                  "words": [{"t": "", "box": [0, 0, 10, 10], "lang": "src", "style": "normal"},
                            {"t": "ok", "box": None, "lang": "src", "style": "normal"}]}]}
_page_bad = rc.build_page(_raw_bad_word, 1, (100, 100), "m", "s.pdf")
check("build_page() drops words with empty text or an unparseable box", _page_bad["blocks"][0]["words"] == [])


# ---------- chunks.chunks_for_page() / _split_by_blocks() ----------

check("chunks_for_page() keeps a short page as one chunk",
      chunks_for_page({"text": "short page text", "blocks": []}) == ["short page text"])

_long_blocks = [{"reading_order": i, "text": "word " * 200} for i in range(4)]
_long_text = "\n".join(b["text"] for b in _long_blocks)
_chunks = chunks_for_page({"text": _long_text, "blocks": _long_blocks})
check("chunks_for_page() splits a long page into more than one chunk", len(_chunks) > 1)
check("_split_by_blocks() never splits a single block's text across two chunks",
      all(any(b["text"] in c for c in _chunks) for b in _long_blocks))
check("chunks_for_page() on an all-empty page returns one empty-string chunk (never a crash)",
      chunks_for_page({"text": "", "blocks": []}) == [""])


# ---------- download.detect() ----------

import fitz  # noqa: E402

def _mkpdf(text: str) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    f = Path(tempfile.mkstemp(suffix=".pdf")[1])
    doc.save(str(f))
    doc.close()
    return f


_fr_pdf = _mkpdf("Le livre et la parole dans le silence pour une étude des sutras")
_en_pdf = _mkpdf("The study of the book and the silence for those with practice")
try:
    check("detect() reads French PDF text as fr", detect(_fr_pdf) == "fr")
    check("detect() reads English PDF text as en", detect(_en_pdf) == "en")
finally:
    _fr_pdf.unlink(missing_ok=True)
    _en_pdf.unlink(missing_ok=True)


# ---------- recognize.link_book() (writes to disk, no network) ----------

_tmp = Path(tempfile.mkdtemp())
try:
    rc.set_stage_dir(_tmp)
    rc.configure("fr", "linkbook_test")
    rc.JSON_DIR.mkdir(parents=True, exist_ok=True)
    rc.IMG_DIR.mkdir(parents=True, exist_ok=True)

    page1 = rc.build_page({
        "printed_page_number": "1",
        "blocks": [{"block_id": "b1", "type": "paragraph", "box": [0, 0, 100, 1000],
                    "words": [{"t": "Hello", "box": [0, 0, 50, 200], "lang": "src", "style": "normal"}]}],
    }, 1, (100, 100), "m", "s.pdf")
    page2 = rc.build_page({
        "printed_page_number": "2",
        "blocks": [{"block_id": "b1", "type": "footnote", "parent_block_id": "", "box": [0, 0, 100, 1000],
                    "words": [{"t": "World", "box": [0, 0, 50, 200], "lang": "src", "style": "normal"}]},
                   {"block_id": "b2", "type": "page_number", "box": [900, 900, 950, 950],
                    "words": [{"t": "2", "box": [900, 900, 950, 950], "lang": "other", "style": "normal"}]}],
    }, 2, (100, 100), "m", "s.pdf")
    (rc.JSON_DIR / "page_0001.json").write_text(json.dumps(page1), encoding="utf-8")
    (rc.JSON_DIR / "page_0002.json").write_text(json.dumps(page2), encoding="utf-8")

    rc.SRC_PDF = None
    n = rc.link_book()
    check("link_book() returns the number of page files it linked", n == 2)

    idx = json.loads((rc.JSON_DIR / "index.json").read_text(encoding="utf-8"))
    check("link_book() writes index.json with page_count == number of pages", idx["page_count"] == 2)
    check("link_book() falls back to len(pages) for total_pages when SRC_PDF is unset (no PDF to open)",
          idx["total_pages"] == 2)

    linked1 = json.loads((rc.JSON_DIR / "page_0001.json").read_text(encoding="utf-8"))
    linked2 = json.loads((rc.JSON_DIR / "page_0002.json").read_text(encoding="utf-8"))
    check("link_book() numbers real (non-furniture) blocks across the whole book in reading order",
          linked1["blocks"][0]["lrm"]["chunk_number_in_lrm"] == 1
          and linked2["blocks"][0]["lrm"]["chunk_number_in_lrm"] == 2)
    check("link_book() excludes page furniture (page_number) from the LRM sequence",
          linked2["blocks"][1]["lrm"]["chunk_number_in_lrm"] is None
          and linked2["blocks"][1]["lrm"]["is_translation_unit"] is False)
    check("link_book() links prev_chunk_id/next_chunk_id across pages",
          linked2["blocks"][0]["lrm"]["prev_chunk_id"] == linked1["blocks"][0]["id"]
          and linked1["blocks"][0]["lrm"]["next_chunk_id"] == linked2["blocks"][0]["id"])
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


# ---------- upload.sync_to_supabase() against a fully faked Supabase client ----------

class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table):
        self.table = table
        self._filters = {}
        self._payload = None
        self._op = "select"

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self._filters[k] = v
        return self

    def upsert(self, rows, on_conflict=None):
        self._op, self._payload = "upsert", rows
        return self

    def delete(self):
        self._op = "delete"
        return self

    def in_(self, col, ids):
        self._filters[col] = ("in", ids)
        return self

    def execute(self):
        # simulate Postgres's generated columns (source_key/language/page_number/title are
        # `generated always as ("rowJSON"->>'...') stored` in sql/create_lrm_tables.sql, not
        # set directly by upsert() -- see the real schema)
        rows = [{**r, **{k: r["rowJSON"].get(k) for k in ("source_key", "language", "page_number", "title")}}
                for r in self.table._rows]
        if self._op == "select":
            out = rows
            for k, v in self._filters.items():
                if isinstance(v, tuple) and v[0] == "in":
                    out = [r for r in out if r.get(k) in v[1]]
                else:
                    out = [r for r in out if r.get(k) == v]
            return FakeResult(out)
        if self._op == "upsert":
            for row in (self._payload if isinstance(self._payload, list) else [self._payload]):
                self.table._rows = [r for r in self.table._rows if r["rowGUID"] != row["rowGUID"]]
                self.table._rows.append(row)
            return FakeResult(self._payload)
        if self._op == "delete":
            ids = self._filters.get("rowGUID", ("in", []))[1]
            deleted = {r["rowGUID"] for r in self.table._rows if r["rowGUID"] in ids}
            self.table._rows = [r for r in self.table._rows if r["rowGUID"] not in ids]
            if self.table.name == "lrm_source_table" and deleted:
                # simulate the real schema's "rowOwnerGUID ... references lrm_source_table(rowGUID)
                # on delete cascade" (sql/create_lrm_tables.sql) -- deleting a source deletes its pages
                pages = self.table.db.tables["lrm_page_table"]
                pages._rows = [r for r in pages._rows if r["rowOwnerGUID"] not in deleted]
            return FakeResult(None)
        raise AssertionError(f"unhandled op {self._op}")


class FakeTable:
    def __init__(self, db, name):
        self.db = db
        self.name = name
        self._rows = []

    def select(self, *_a, **_k):
        return FakeQuery(self).select()

    def upsert(self, rows, on_conflict=None):
        return FakeQuery(self).upsert(rows, on_conflict)

    def delete(self):
        return FakeQuery(self).delete()

    def eq(self, k, v):
        return FakeQuery(self).eq(k, v)


class FakeSupabase:
    def __init__(self):
        self.tables = {name: FakeTable(self, name) for name in ("lrm_source_table", "lrm_page_table")}

    def table(self, name):
        return self.tables[name]


def _write_source(root: Path, lang: str, key: str, pages: list[int]) -> None:
    d = root / lang / key / "json"
    d.mkdir(parents=True, exist_ok=True)
    for n in pages:
        (d / f"page_{n:04d}.json").write_text(json.dumps({
            "page": n, "blocks": [{"text": f"page {n} text"}],
        }), encoding="utf-8")
    (d / "index.json").write_text(json.dumps({"total_pages": max(pages)}), encoding="utf-8")


_fake_sb = FakeSupabase()
_orig_make_client = up.make_supabase_client
up.make_supabase_client = lambda: _fake_sb
_tmp2 = Path(tempfile.mkdtemp())
try:
    _write_source(_tmp2, "fr", "book_a", [1, 2, 3])
    n = up.sync_to_supabase(_tmp2)
    check("sync_to_supabase() uploads one source dir with pages on disk", n == 1)
    check("sync_to_supabase() upserts one lrm_source_table row", len(_fake_sb.tables["lrm_source_table"]._rows) == 1)
    check("sync_to_supabase() upserts one lrm_page_table row per page json", len(_fake_sb.tables["lrm_page_table"]._rows) == 3)

    # remove page 2 from disk and rerun: sync should delete the now-stale Supabase row for it
    (_tmp2 / "fr" / "book_a" / "json" / "page_0002.json").unlink()
    up.sync_to_supabase(_tmp2)
    remaining_pages = sorted(r["orderInList"] for r in _fake_sb.tables["lrm_page_table"]._rows)
    check("sync_to_supabase() deletes a page from Supabase once its json file is removed from disk",
          remaining_pages == [1, 3])

    # remove the whole source dir and rerun: the source (and its pages) should be dropped
    shutil.rmtree(_tmp2 / "fr" / "book_a")
    n2 = up.sync_to_supabase(_tmp2)
    check("sync_to_supabase() returns 0 and empties both tables once the last source dir is gone",
          n2 == 0 and not _fake_sb.tables["lrm_source_table"]._rows and not _fake_sb.tables["lrm_page_table"]._rows)
finally:
    up.make_supabase_client = _orig_make_client
    shutil.rmtree(_tmp2, ignore_errors=True)


print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All checks passed.")
    sys.exit(0)
