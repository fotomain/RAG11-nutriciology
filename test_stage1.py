"""Offline tests for reusable_code/stage1 (extract & chunk, load, verify, pipeline) with fake clients and
temporary folders. Run: .venv/bin/python test_stage1.py"""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, ".")

from reusable_code.stage1 import common, extract_chunk as ec, load, pipeline, verify  # noqa: E402

FAILURES = []


def check(label, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILURES.append(label)


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------------------------- fake DB
class FakeDB:
    """Just enough of supabase-py: table().select().range()/upsert()/delete().in_(), rpc()."""
    def __init__(self):
        self.tables = {}
        self.upserts = []
        self.deleted = []

    def table(self, name):
        return _Q(self, name)

    def rpc(self, name, params):
        rows = list(self.tables.get("rag11_chunks_child_table", {}).values())[: params["match_count"]]
        return SimpleNamespace(execute=lambda: SimpleNamespace(
            data=[{**r, "cosine_distance": 0.1} for r in rows]))


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.mode, self.rng = db, name, "select", None

    def select(self, *_a, **_k): return self
    def range(self, a, b): self.rng = (a, b); return self
    def upsert(self, rows):
        self.mode, self.rows = "upsert", rows; return self
    def delete(self): self.mode = "delete"; return self
    def in_(self, col, vals): self.vals = vals; return self

    def execute(self):
        store = self.db.tables.setdefault(self.name, {})
        if self.mode == "upsert":
            self.db.upserts.append((self.name, len(self.rows)))
            for r in self.rows:
                store[r["rowGUID"]] = r
            return SimpleNamespace(data=self.rows)
        if self.mode == "delete":
            for g in self.vals:
                store.pop(g, None)
            self.db.deleted.extend(self.vals)
            return SimpleNamespace(data=[])
        rows = list(store.values())
        a, b = self.rng
        return SimpleNamespace(data=rows[a:b + 1])


class FakeVoyage:
    def __init__(self):
        self.calls = []

    def embed(self, texts, model, input_type):
        self.calls.append((list(texts), input_type))
        return SimpleNamespace(embeddings=[[float(len(t))] * 1024 for t in texts])


# ---------------------------------------------------------------------------------------------- common
check("strip_bad_unicode removes NUL recursively", common.strip_bad_unicode({"a": ["x\x00y", {"b": "\x00"}]}) == {"a": ["xy", {"b": ""}]})
r1 = {"rowGUID": "g", "rowJSON": {"t": "a"}, "embedding": [1.0]}
check("row_hash ignores the embedding", common.row_hash(r1) == common.row_hash({**r1, "embedding": [9.0]}))
check("row_hash changes with content", common.row_hash(r1) != common.row_hash({**r1, "rowJSON": {"t": "b"}}))
check("row_hash is stable across NUL noise", common.row_hash({"rowGUID": "g", "rowJSON": {"t": "a\x00"}}) == common.row_hash({"rowGUID": "g", "rowJSON": {"t": "a"}}))

with tempfile.TemporaryDirectory() as tmp:
    paths = common.get_paths(tmp)
    try:
        common.load_local_data(paths)
        check("load_local_data with no manifests raises a clear error", False)
    except (RuntimeError, FileNotFoundError) as e:
        check("load_local_data with no manifests raises a clear error", "stage 1.1" in str(e) or isinstance(e, FileNotFoundError))

    paths.output_root.mkdir(parents=True)
    src_guid = common.deterministic_uuid("source:file1")
    write_json(paths.sources_manifest_dir / "source_row-1.json",
               {"rowGUID": src_guid, "rowOwnerGUID": src_guid, "rowParentGUID": None, "orderInList": 1,
                "rowJSON": {"source_key": "source1", "filename": "a.pdf"}})
    d1 = paths.output_root / "source1"
    write_json(d1 / "parent_chunk-2.json", {"parent_id": "source1-p2", "source_key": "source1", "source_row_guid": src_guid, "text": "P2"})
    write_json(d1 / "parent_chunk-10.json", {"parent_id": "source1-p10", "source_key": "source1", "source_row_guid": src_guid, "text": "P10"})
    write_json(d1 / "child_chunk-parent2-chunk1.json", {"child_id": "source1-p2-c1", "parent_id": "source1-p2", "source_key": "source1", "source_row_guid": src_guid, "text": "C"})
    write_json(d1 / "child_chunk-parent10-chunk3.json", {"child_id": "source1-p10-c3", "parent_id": "source1-p10", "source_key": "source1", "text": "no owner in file"})
    (d1 / "_cache_pages.json").write_text("[]")
    (paths.output_root / "source9").mkdir()      # stale folder with no manifest row
    write_json(paths.output_root / "source9" / "parent_chunk-1.json", {"parent_id": "source9-p1"})

    local = common.load_local_data(paths, verbose=False)
    check("discover_source_keys ignores folders without a manifest row", local.source_keys == ["source1"])
    check("parent files sorted numerically (2 before 10), order parsed from the file name",
          [o for o, _ in local.parents_by_source["source1"]] == [2, 10])
    check("child rowOwnerGUID falls back to the manifest when the file has none",
          [r["rowOwnerGUID"] for r in local.child_rows()] == [src_guid, src_guid])
    prow = local.parent_rows()[0]
    check("parent row shape (deterministic guid, no parent, orderInList from file name)",
          prow["rowGUID"] == common.deterministic_uuid("parent:source1-p2") and prow["rowParentGUID"] is None and prow["orderInList"] == 2)
    crow = local.child_rows()[0]
    check("child rowParentGUID == the parent row's rowGUID (FK always satisfied)", crow["rowParentGUID"] == prow["rowGUID"])
    check("LocalData.counts", "1 source row(s), 2 parent row(s), 2 child row(s)" in local.counts())

# ------------------------------------------------------------------------------------------ extract_chunk
text = " ".join(f"word{i}" for i in range(3000))
chunks = ec.build_child_chunks(text)
check("build_child_chunks: windows of at most 400 tokens", chunks and all(ec.token_len(c) <= 400 for c in chunks))
step_expected = int(400 * (1 - 0.125))
n_tokens = ec.token_len(text)
check("build_child_chunks: 12.5% overlap (step 350) gives the expected number of chunks",
      len(chunks) == 1 + -(-(n_tokens - 400) // step_expected))
check("build_child_chunks: empty text gives no chunks", ec.build_child_chunks("") == [])
custom = ec.child_pieces_for_section({"text": "x", "children": [{"text": "a"}, {"text": "  "}, {"text": "b", "chunk_type": "table"}]})
check("child_pieces_for_section: custom children kept verbatim, blanks dropped, chunk_type defaults",
      custom == [{"text": "a", "chunk_type": "prose"}, {"text": "b", "chunk_type": "table"}])
check("contextual_header shows 1-based pages", ec.contextual_header("f.pdf", {"title": "T", "start_page": 59, "end_page": 60})
      == "[Source: f.pdf | Section: T | Pages 60-61]")

with tempfile.TemporaryDirectory() as tmp:
    cfg = ec.Config(paths=common.get_paths(tmp), max_pages=100, drive_folder_url=ec.DEFAULT_DRIVE_FOLDER)
    check("Drive folder id parsed from the URL", cfg.drive_folder_id == "1GwS2oNWkn_aLE1eDTbkHW73Ljun_aM4I")

    from stage1_1_eda_packages import KNOWN_SOURCE_EDA_META, SKIPPED_FILENAMES
    known = list(KNOWN_SOURCE_EDA_META)
    skipped = list(SKIPPED_FILENAMES)[0]
    listing = [{"file_id": "id-new", "name": "zzz_new_book.pdf"}, {"file_id": "id-k2", "name": known[1]},
               {"file_id": "id-skip", "name": skipped}, {"file_id": "id-k1", "name": known[0]}]
    sources = ec.build_sources(cfg, drive_files=listing)
    check("build_sources: known books keep their historical order, new files come after, skipped are dropped",
          [s["filename"] for s in sources.values()] == [known[0], known[1], "zzz_new_book.pdf"])
    check("build_sources: unknown book gets a slot with structure 'unknown'", sources["source3"]["structure"] == "unknown" and sources["source3"]["expected_pages"] is None)
    check("build_sources: input/output folders created", (cfg.paths.input_root / "source3").is_dir() and (cfg.paths.output_root / "source1").is_dir())
    check("build_sources: row_guid is deterministic", sources["source1"]["row_guid"] == common.deterministic_uuid("source:id-k1"))

    # downloads: PDFs already present -> no gdown; fetched_at kept while the PDF is unchanged
    import fitz
    for key, src in sources.items():
        doc = fitz.open(); doc.new_page(); doc.save(str(cfg.paths.input_root / key / src["filename"])); doc.close()
    dl1, info1 = ec.download_sources(cfg, sources)
    ec.write_source_manifests(cfg, sources, info1)
    dl2, info2 = ec.download_sources(cfg, sources)
    check("download_sources: existing PDFs are reused (paths point at them)", all(p.exists() for p in dl1.values()))
    check("download_sources: fetched_at is stable across runs while the PDF is unchanged",
          all(info1[k]["fetched_at"] == info2[k]["fetched_at"] for k in sources))
    manifest = json.loads((cfg.paths.sources_manifest_dir / "source_row-1.json").read_text())
    check("source manifest: self-owned, parentless, keyed by source_key",
          manifest["rowOwnerGUID"] == manifest["rowGUID"] and manifest["rowParentGUID"] is None and manifest["rowJSON"]["source_key"] == "source1")

    # page extraction + cache (cap in the cache name)
    pages = ec.extract_pages(cfg, "source1", dl1["source1"])
    check("extract_pages: one entry per real page, cached under a cap-specific name",
          len(pages) == 1 and (cfg.paths.output_root / "source1" / "_cache_pages_max100.json").exists())

    # write_chunks: files, stale removal, token_count without header
    secs = [{"title": "Sec A", "level": 1, "start_page": 0, "end_page": 1, "text": text},
            {"title": "Sec B", "level": 1, "start_page": 2, "end_page": 2, "text": "short text", "block_type": ["x"]}]
    out_dir = cfg.paths.output_root / "source1"
    (out_dir / "parent_chunk-99.json").write_text("{}")
    (out_dir / "child_chunk-parent99-chunk1.json").write_text("{}")
    counts = ec.write_chunks(cfg, sources, "source1", secs)
    check("write_chunks: counts", counts == (2, len(chunks) + 1))
    check("write_chunks: stale files from a previous run are removed", not (out_dir / "parent_chunk-99.json").exists()
          and not (out_dir / "child_chunk-parent99-chunk1.json").exists())
    child = json.loads((out_dir / "child_chunk-parent2-chunk1.json").read_text())
    check("write_chunks: child text = header + body, token_count excludes the header, ids follow the file names",
          child["text"].startswith("[Source: ") and child["text"].endswith("short text") and child["token_count"] == ec.token_len("short text")
          and child["child_id"] == "source1-p2-c1" and child["source_row_guid"] == sources["source1"]["row_guid"])
    check("write_chunks output is loadable by the stage 1.2/1.9 loaders",
          len(common.load_parent_files(cfg.paths, "source1")) == 2 and len(common.load_child_files(cfg.paths, "source1")) == len(chunks) + 1)

# ---------------------------------------------------------------------------------------------- load
with tempfile.TemporaryDirectory() as tmp:
    paths = common.get_paths(tmp)
    db, voy = FakeDB(), FakeVoyage()
    ctx = load.LoaderContext(supabase=db, voyage=voy, paths=paths, stagger_s=0)
    rows = [{"rowGUID": f"g{i}", "rowJSON": {"text": f"t{i}"}, "embedding": [0.1]} for i in range(5)]
    check("upsert_batches: first load sends everything", load.upsert_batches(ctx, "t", rows) == 5)
    check("upsert_batches: unchanged rows are skipped", load.upsert_batches(ctx, "t", rows) == 0)
    rows[2]["rowJSON"]["text"] = "CHANGED"
    check("upsert_batches: a changed row is re-sent (and only it)", load.upsert_batches(ctx, "t", rows) == 1 and db.tables["t"]["g2"]["rowJSON"]["text"] == "CHANGED")
    rows[3]["embedding"] = [9.9]
    check("upsert_batches: an embedding-only difference is not a change", load.upsert_batches(ctx, "t", rows) == 0)
    (paths.checkpoint_dir / "legacy_upserted_row_guids.json").write_text(json.dumps(["g0", "g1"]))
    check("legacy list checkpoint: re-upserted once, then stable", load.upsert_batches(ctx, "legacy", rows[:2]) == 2 and load.upsert_batches(ctx, "legacy", rows[:2]) == 0)
    ctx2 = load.LoaderContext(supabase=FakeDB(), voyage=voy, paths=paths, stagger_s=0, insert_batch_size=2)
    check("upsert_batches honours the batch size", load.upsert_batches(ctx2, "b", rows) == 5 and [n for _t, n in ctx2.supabase.upserts] == [2, 2, 1])

class TimeoutErr(Exception):
    code = "57014"


class TimeoutDB(FakeDB):
    """Rejects any upsert of more than `limit` rows with a Postgres statement timeout."""
    def __init__(self, limit):
        super().__init__(); self.limit, self.attempts = limit, []

    def table(self, name):
        q = _Q(self, name); real = q.execute
        def execute():
            if q.mode == "upsert":
                self.attempts.append(len(q.rows))
                if len(q.rows) > self.limit:
                    raise TimeoutErr("canceling statement due to statement timeout")
            return real()
        q.execute = execute
        return q


with tempfile.TemporaryDirectory() as tmp:
    tdb = TimeoutDB(limit=30)
    tctx = load.LoaderContext(supabase=tdb, voyage=FakeVoyage(), paths=common.get_paths(tmp), stagger_s=0)
    many = [{"rowGUID": f"r{i}", "rowJSON": {"t": i}, "embedding": [0.0]} for i in range(100)]
    check("statement timeout: a 100-row batch is split until it fits, nothing is lost",
          load.upsert_batches(tctx, "t", many) == 100 and len(tdb.tables["t"]) == 100)
    check("statement timeout: it splits (100 -> 50+50 -> 25s) instead of retrying the same size, no backoff sleeps",
          tdb.attempts[0] == 100 and tdb.attempts.count(100) == 1 and max(a for a in tdb.attempts[1:]) <= 50)
    bad = TimeoutDB(limit=0)
    bctx = load.LoaderContext(supabase=bad, voyage=FakeVoyage(), paths=common.get_paths(tmp), stagger_s=0)
    import reusable_code.retry as _retry_mod
    _sleep, _retry_mod.time.sleep = _retry_mod.time.sleep, lambda s: None
    try:
        load.upsert_batches(bctx, "u", many[:8])
        check("statement timeout on a tiny batch is retried and finally raised", False)
    except TimeoutErr:
        check("statement timeout on a tiny batch is retried and finally raised", len(bad.attempts) == 8)
    finally:
        _retry_mod.time.sleep = _sleep

with tempfile.TemporaryDirectory() as tmp:
    paths = common.get_paths(tmp)
    src_guid = common.deterministic_uuid("source:file1")
    write_json(paths.sources_manifest_dir / "source_row-1.json",
               {"rowGUID": src_guid, "rowOwnerGUID": src_guid, "rowParentGUID": None, "orderInList": 1, "rowJSON": {"source_key": "source1"}})
    for p in (1, 2):
        write_json(paths.output_root / "source1" / f"parent_chunk-{p}.json", {"parent_id": f"source1-p{p}", "source_key": "source1", "source_row_guid": src_guid, "text": "P"})
        for c in (1, 2):
            write_json(paths.output_root / "source1" / f"child_chunk-parent{p}-chunk{c}.json",
                       {"child_id": f"source1-p{p}-c{c}", "parent_id": f"source1-p{p}", "source_key": "source1", "source_row_guid": src_guid, "text": f"child {p}.{c}"})
    db, voy = FakeDB(), FakeVoyage()
    ctx = load.LoaderContext(supabase=db, voyage=voy, paths=paths, stagger_s=0, voyage_batch_size=3)
    res = load.run_stage1_2(ctx=ctx)
    check("run_stage1_2: 1 source, 2 parents, 4 children loaded", (res.n_sources, res.n_parents, res.n_children) == (1, 2, 4))
    check("embeddings keep input order across batches (voyage batches of 3)",
          [len(c[0]) for c in voy.calls] == [3, 1] or sorted(len(c[0]) for c in voy.calls) == [1, 3])
    emb = {r["rowJSON"]["child_id"]: r["embedding"][0] for r in db.tables["rag11_chunks_child_table"].values()}
    check("each child got the embedding of ITS OWN text (fake embeds len(text))",
          all(emb[f"source1-p{p}-c{c}"] == float(len(f"child {p}.{c}")) for p in (1, 2) for c in (1, 2)))
    n_calls = sum(len(c[0]) for c in voy.calls)
    res2 = load.run_stage1_2(ctx=ctx)
    check("second run: nothing new to embed or send", res2.n_children == 0 and sum(len(c[0]) for c in voy.calls) == n_calls)
    # change one child on disk -> only that one is re-embedded
    write_json(paths.output_root / "source1" / "child_chunk-parent2-chunk2.json",
               {"child_id": "source1-p2-c2", "parent_id": "source1-p2", "source_key": "source1", "source_row_guid": src_guid, "text": "child 2.2 EDITED"})
    res3 = load.run_stage1_2(ctx=ctx)
    check("editing one chunk re-embeds and re-sends exactly one child", res3.n_children == 1 and sum(len(c[0]) for c in voy.calls) == n_calls + 1)

    # orphans: a child and a parent in the DB with no local file; plus rows of a source we don't have locally
    other_owner = "some-other-source-guid"
    db.tables["rag11_chunks_child_table"]["orphan-child"] = {"rowGUID": "orphan-child", "rowOwnerGUID": src_guid}
    db.tables["rag11_chunks_parent_table"]["orphan-parent"] = {"rowGUID": "orphan-parent", "rowOwnerGUID": src_guid}
    db.tables["rag11_chunks_child_table"]["foreign-child"] = {"rowGUID": "foreign-child", "rowOwnerGUID": other_owner}
    local = common.load_local_data(paths, verbose=False)
    check("prune_orphans(prune=False) reports but deletes nothing", load.prune_orphans(ctx, local) == 2 and not db.deleted)
    check("prune_orphans(prune=True) deletes only orphans of local sources",
          load.prune_orphans(ctx, local, prune=True) == 2 and sorted(db.deleted) == ["orphan-child", "orphan-parent"]
          and "foreign-child" in db.tables["rag11_chunks_child_table"])

    # ---------------------------------------------------------------------------------------- verify
    ok = verify.Report()
    snap = verify.fetch_db(db, verbose=False)
    verify.compare_sources(local, snap, ok); verify.compare_parents(local, snap, ok); verify.compare_children(local, snap, ok)
    check("verify: after a clean load only the foreign-owner row is 'orphaned'",
          ok.source_ok == 1 and ok.parent_ok == 2 and ok.child_ok == 4 and ok.child_orphaned == ["foreign-child"] and not ok.parent_orphaned)
    db.tables["rag11_chunks_child_table"].pop("foreign-child")
    db.tables["rag11_chunks_child_table"][common.deterministic_uuid("child:source1-p1-c1")]["embedding"] = [0.1] * 5
    db.tables["rag11_chunks_child_table"][common.deterministic_uuid("child:source1-p1-c2")]["rowJSON"] = {"child_id": "source1-p1-c2", "text": "stale"}
    db.tables["rag11_chunks_parent_table"].pop(common.deterministic_uuid("parent:source1-p2"))
    db.tables["rag11_data_sources"][src_guid]["rowJSON"] = {"source_key": "source1", "extra": True}
    bad = verify.Report()
    snap = verify.fetch_db(db, verbose=False)
    verify.compare_sources(local, snap, bad); verify.compare_parents(local, snap, bad); verify.compare_children(local, snap, bad)
    check("verify: detects a bad embedding length, a stale rowJSON, a missing parent and a changed source row",
          len(bad.child_missing_embedding) == 1 and len(bad.child_mismatched) == 1 and len(bad.parent_missing) == 1
          and bad.source_mismatched == ["source1"] and not bad.passed and bad.total_issues == 4)
    check("verify: pgvector returned as a string still counts its length",
          verify.embedding_length("[0.1,0.2,0.3]") == 3 and verify.embedding_length(None) == 0 and verify.embedding_length([1, 2]) == 2)
    lines = verify.counts_table_lines(local, snap)
    check("counts table flags the drifted source", lines[1].endswith("<-- mismatch"))
    check("a fully matching report passes", ok.child_orphaned.clear() is None and verify.Report().passed)

# --------------------------------------------------------------------------------------------- pipeline
check("select_stages", pipeline.select_stages() == ["1.1", "1.2", "1.9"] and pipeline.select_stages("1.9") == ["1.9"]
      and pipeline.select_stages(None, "1.2") == ["1.2", "1.9"])
calls = []
ec.run_stage1_1 = lambda root=None: calls.append("1.1")
load.run_stage1_2 = lambda root=None, prune=False: calls.append(f"1.2 prune={prune}")
verify.run_stage1_9 = lambda root=None: SimpleNamespace(passed=True)
check("pipeline.run: all stages in order, exit 0 on PASS, --prune-orphans reaches stage 1.2",
      pipeline.run(prune_orphans=True) == 0 and calls == ["1.1", "1.2 prune=True"])
verify.run_stage1_9 = lambda root=None: SimpleNamespace(passed=False)
check("pipeline.run: exit 1 when verification finds issues", pipeline.run(["1.9"]) == 1)


def boom(root=None, prune=False):
    raise RuntimeError("boom")


load.run_stage1_2 = boom
calls.clear()
verify.run_stage1_9 = lambda root=None: calls.append("verify") or SimpleNamespace(passed=True)
check("pipeline.run: a crash stops the run with exit 2 (verify does not run)", pipeline.run(["1.2", "1.9"]) == 2 and calls == [])
check("pipeline.main parses --only and --from", pipeline.main(["--only", "1.9"]) == 0)

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(" -", f)
    sys.exit(1)
print("All checks passed.")
