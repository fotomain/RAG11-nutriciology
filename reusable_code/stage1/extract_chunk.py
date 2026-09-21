"""Stage 1.1 -- extract text from the source PDFs and write hierarchical chunks.

    list the Drive folder -> download missing PDFs -> write source manifests -> extract page text (cached)
    -> detect sections (one module per book in stage1_1_eda_packages/) -> write parent/child chunk JSON files

Each step is a function so the notebook can show them one by one; ``run_stage1_1()`` runs them all.
Every step is idempotent: the Drive listing is cheap, downloads skip files already on disk, page text is cached.

Config (``.env``):
    MAX_NUMBER_OF_PAGES_TO_USE   pages of text extracted per PDF. Unset = 100 (smoke test), NONE = no cap (real run).
                                 Section boundaries still come from the whole PDF; sections starting past the cap
                                 just have empty text.
    GOOGLE_DRIVE_SOURCES_FOLDER  public "anyone with the link" Drive folder holding the PDFs.
"""
import json
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..env import optional_env, optional_env_limit
from .common import Paths, banner, deterministic_uuid, get_paths

DEFAULT_MAX_PAGES = 100
DEFAULT_DRIVE_FOLDER = "https://drive.google.com/drive/folders/1GwS2oNWkn_aLE1eDTbkHW73Ljun_aM4I?usp=drive_link"
CHILD_TARGET_TOKENS = 400
CHILD_OVERLAP_PCT = 0.125


# --------------------------------------------------------------------------------------------- config


@dataclass(frozen=True)
class Config:
    paths: Paths
    max_pages: Optional[int]      # None = extract text for every page
    drive_folder_url: str

    @property
    def drive_folder_id(self) -> str:
        return drive_folder_id(self.drive_folder_url)


def load_config(root=None, *, verbose: bool = True) -> Config:
    cfg = Config(
        paths=get_paths(root),
        max_pages=optional_env_limit("MAX_NUMBER_OF_PAGES_TO_USE", DEFAULT_MAX_PAGES),
        drive_folder_url=optional_env("GOOGLE_DRIVE_SOURCES_FOLDER", DEFAULT_DRIVE_FOLDER) or DEFAULT_DRIVE_FOLDER,
    )
    if verbose:
        print("MAX_NUMBER_OF_PAGES_TO_USE =", cfg.max_pages if cfg.max_pages else "NONE (full run)")
        print("Drive folder:", cfg.drive_folder_url)
    return cfg


def drive_folder_id(url: str) -> str:
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
    if not m:
        raise ValueError(f"Could not find a Drive folder id in: {url}")
    return m.group(1)


# --------------------------------------------------------------------------------- Drive listing / sources


def list_drive_folder_files(folder_id: str) -> List[dict]:
    """Every file directly in the public Drive folder, WITHOUT downloading (needs gdown >= 6.1 for
    ``skip_download=``; older versions fall back to downloading into a temp dir just to list names)."""
    import gdown
    try:
        records = gdown.download_folder(id=folder_id, skip_download=True, quiet=True, use_cookies=False)
        files = [{"file_id": r.id, "name": Path(r.path).name} for r in (records or [])]
    except TypeError:
        print("  [list_drive_folder_files] installed gdown has no skip_download= support; listing by downloading "
              "into a temp folder instead (upgrade gdown>=6.1 to skip this extra download).")
        with tempfile.TemporaryDirectory() as tmp:
            gdown.download_folder(id=folder_id, output=tmp, quiet=True, use_cookies=False)
            files = [{"file_id": None, "name": p.name} for p in sorted(Path(tmp).rglob("*")) if p.is_file()]
    if not files:
        raise RuntimeError(f"No files found in Drive folder {folder_id}. Confirm the folder is still shared as "
                           "'Anyone with the link' (GOOGLE_DRIVE_SOURCES_FOLDER).")
    return files


def build_sources(cfg: Config, *, drive_files: Optional[List[dict]] = None) -> Dict[str, dict]:
    """SOURCES = {"source1": {file_id, filename, expected_pages, structure, row_guid}, ...}.

    Built from the Drive listing (or ``drive_files=`` for tests). Known books keep their historical slot
    (order of ``KNOWN_SOURCE_EDA_META``); new files are appended by name; files a module marks unusable are
    skipped before any slot number is assigned. Also creates the input/output folders.
    """
    from stage1_1_eda_packages import KNOWN_SOURCE_EDA_META, SKIPPED_FILENAMES
    listing = drive_files if drive_files is not None else list_drive_folder_files(cfg.drive_folder_id)
    known_order = list(KNOWN_SOURCE_EDA_META.keys())

    def order_key(f):
        try:
            return (0, known_order.index(f["name"]))
        except ValueError:
            return (1, f["name"])

    usable = []
    for f in sorted(listing, key=order_key):
        reason = SKIPPED_FILENAMES.get(f["name"])
        if reason:
            print(f'  [skip] {f["name"]}: {reason}')
            continue
        usable.append(f)
    print(f"Drive folder {cfg.drive_folder_id}: {len(listing)} file(s) found, {len(usable)} usable -> "
          + ", ".join(f["name"] for f in usable))

    sources = {}
    for idx, f in enumerate(usable, start=1):
        meta = KNOWN_SOURCE_EDA_META.get(f["name"], {"expected_pages": None, "structure": "unknown"})
        sources[f"source{idx}"] = {
            "file_id": f["file_id"],
            "filename": f["name"],
            "expected_pages": meta["expected_pages"],
            "structure": meta["structure"],
            # This source's row in rag11_data_sources; also the rowOwnerGUID of all its parent/child rows.
            "row_guid": deterministic_uuid(f"source:{f['file_id'] or f['name']}"),
        }
    for key in sources:
        (cfg.paths.input_root / key).mkdir(parents=True, exist_ok=True)
        (cfg.paths.output_root / key).mkdir(parents=True, exist_ok=True)
    cfg.paths.sources_manifest_dir.mkdir(parents=True, exist_ok=True)
    return sources


# ---------------------------------------------------------------------------------------------- download


def download_if_missing(cfg: Config, sources: Dict[str, dict], source_key: str) -> Path:
    """Ensure ./stage1_eda_input/<source_key>/<filename> exists (gdown from Drive if not). Safe to re-run."""
    import gdown
    src = sources[source_key]
    target = cfg.paths.input_root / source_key / src["filename"]
    if target.exists() and target.stat().st_size > 0:
        print(f"[{source_key}] already present: {target.name} ({target.stat().st_size / 1e6:.1f} MB)")
        return target
    if not src["file_id"]:
        raise RuntimeError(
            f"[{source_key}] no Drive file_id for {src['filename']} (the installed gdown fell back to the "
            f"no-skip_download listing; upgrade gdown>=6.1 or download the file manually into {target})."
        )
    print(f"[{source_key}] downloading {src['filename']} (Drive id {src['file_id']}) -> {target}")
    gdown.download(id=src["file_id"], output=str(target), quiet=False)
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError(f"[{source_key}] download failed or produced an empty file at {target}. If Drive shows "
                           "a warning page instead of the PDF, re-run, or download it manually into that path.")
    return target


def verify_page_count(sources: Dict[str, dict], source_key: str, path: Path) -> int:
    import fitz
    expected = sources[source_key]["expected_pages"]
    with fitz.open(path) as doc:
        n = doc.page_count
    if expected is None:
        print(f"[{source_key}] {n} pages (no expected-page baseline for this file)")
    else:
        print(f"[{source_key}] {n} pages (expected {expected}) -> {'OK' if n == expected else 'MISMATCH'}")
    return n


def _previous_fetch_info(cfg: Config) -> Dict[str, dict]:
    prev = {}
    for f in cfg.paths.sources_manifest_dir.glob("source_row-*.json"):
        rj = json.loads(f.read_text(encoding="utf-8")).get("rowJSON", {})
        prev[rj.get("source_key")] = rj
    return prev


def download_sources(cfg: Config, sources: Dict[str, dict]) -> Tuple[Dict[str, Path], Dict[str, dict]]:
    """Download whatever is missing (in parallel, max 6 at a time to stay polite to Drive) and verify page counts.

    Returns (downloaded_paths, source_fetch_info). A source keeps its previous ``fetched_at`` while its PDF is
    unchanged (same file name and size); a fresh timestamp on every run would make every source row look
    "changed" to stage 1.2 and "mismatched" to stage 1.9.
    """
    previous = _previous_fetch_info(cfg)

    def fetched_at(key: str, path: Path) -> str:
        prev = previous.get(key, {})
        if (prev.get("filename") == sources[key]["filename"] and prev.get("size_bytes") == path.stat().st_size
                and prev.get("fetched_at")):
            return prev["fetched_at"]
        return datetime.now(timezone.utc).isoformat()

    paths_out, info = {}, {}
    with ThreadPoolExecutor(max_workers=min(6, len(sources) or 1)) as pool:
        futures = {pool.submit(download_if_missing, cfg, sources, key): key for key in sources}
        for fut in as_completed(futures):
            key, path = futures[fut], fut.result()   # raises here if that source's download failed
            n_pages = verify_page_count(sources, key, path)
            paths_out[key] = path
            info[key] = {
                "local_path": str(path.relative_to(cfg.paths.root)),
                "size_bytes": path.stat().st_size,
                "actual_page_count": n_pages,
                "fetched_at": fetched_at(key, path),
            }
    # callers iterate `for key in sources` (never these dicts), so out-of-order completion is harmless
    return paths_out, info


# ------------------------------------------------------------------------------------ source manifests


def build_source_row(cfg: Config, sources: Dict[str, dict], fetch_info: Dict[str, dict], key: str, order: int) -> dict:
    src = sources[key]
    return {
        "rowGUID": src["row_guid"],
        "rowOwnerGUID": src["row_guid"],   # a source is its own tree's root/owner
        "rowParentGUID": None,             # sources sit above everything
        "orderInList": order,
        "rowJSON": {
            "source_key": key,
            "drive_folder_url": cfg.drive_folder_url,
            "drive_folder_id": cfg.drive_folder_id,
            "drive_file_id": src["file_id"],
            "filename": src["filename"],
            "expected_pages": src["expected_pages"],
            "structure": src["structure"],
            **fetch_info[key],
        },
    }


def _write_manifest(cfg, sources, fetch_info, key, order) -> None:
    (cfg.paths.sources_manifest_dir / f"source_row-{order}.json").write_text(
        json.dumps(build_source_row(cfg, sources, fetch_info, key, order), ensure_ascii=False, indent=2),
        encoding="utf-8")


def write_source_manifests(cfg: Config, sources: Dict[str, dict], fetch_info: Dict[str, dict]) -> None:
    """One ``rag11_data_sources``-ready row per source in stage1_eda_output/sources/source_row-N.json
    (stale ones from a previous run are removed first)."""
    for stale in cfg.paths.sources_manifest_dir.glob("source_row-*.json"):
        stale.unlink()
    for order, key in enumerate(sources, start=1):
        _write_manifest(cfg, sources, fetch_info, key, order)
    print(f"Wrote {len(sources)} source row(s) -> {cfg.paths.sources_manifest_dir} (loaded into "
          "rag11_data_sources by stage 1.2)")


# ----------------------------------------------------------------------------------------- page text


def extract_pages(cfg: Config, source_key: str, pdf_path: Path) -> List[str]:
    """Per-page plain text (index 0 = page 1), one entry per REAL page regardless of the cap (so page-number
    arithmetic is never off), cached. With a cap only that many leading pages go through ``get_text()``; later
    pages are "". The cache file name carries the cap so a capped and a full run never reuse each other's cache.
    NUL characters are stripped here: Postgres text/jsonb cannot store them, and stripping only at upsert time
    would leave a permanent local-vs-database mismatch (stage 1.9) on every affected chunk.
    """
    import fitz
    suffix = f"_max{cfg.max_pages}" if cfg.max_pages is not None else ""
    cache_path = cfg.paths.output_root / source_key / f"_cache_pages{suffix}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    limit = float("inf") if cfg.max_pages is None else cfg.max_pages
    pages = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            pages.append((page.get_text("text") if i < limit else "").replace("\x00", ""))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    n_extracted = len(pages) if limit == float("inf") else min(len(pages), int(limit))
    print(f"[{source_key}] cached {len(pages)} page(s), text extracted for {n_extracted} of them -> {cache_path}")
    return pages


def extract_all_pages(cfg: Config, sources: Dict[str, dict], downloaded: Dict[str, Path]) -> Dict[str, List[str]]:
    return {key: extract_pages(cfg, key, downloaded[key]) for key in sources}


# -------------------------------------------------------------------------------------------- sections


def assemble_sections(cfg: Config, sources: Dict[str, dict], downloaded: Dict[str, Path],
                      pages_by_source: Dict[str, List[str]], fetch_info: Dict[str, dict]) -> Dict[str, List[dict]]:
    """Section detection per book, routed by FILENAME to its module in stage1_1_eda_packages/. A file with no
    dedicated module is chunked by the generic fallback (PDF outline -> larger-font headings -> page windows);
    the strategy actually used is recorded in that source's manifest row."""
    from stage1_1_eda_packages import process_source
    sections_by_source = {}
    for order, (key, src) in enumerate(sources.items(), start=1):
        sections, structure, used_fallback = process_source(key, src["filename"], downloaded[key], pages_by_source[key])
        sections_by_source[key] = sections
        if used_fallback:
            src["structure"] = structure
            _write_manifest(cfg, sources, fetch_info, key, order)
    return sections_by_source


# ---------------------------------------------------------------------------------------------- chunking


@lru_cache(maxsize=1)
def _encoding():
    import tiktoken
    return tiktoken.get_encoding("cl100k_base")


def token_len(text: str) -> int:
    return len(_encoding().encode(text))


def build_child_chunks(text: str, target_tokens: int = CHILD_TARGET_TOKENS,
                       overlap_pct: float = CHILD_OVERLAP_PCT) -> List[str]:
    """Fixed windows of ``target_tokens`` tokens, each starting ``target_tokens * (1 - overlap_pct)`` after the last."""
    enc = _encoding()
    tokens = enc.encode(text)
    if not tokens:
        return []
    step = max(1, int(target_tokens * (1 - overlap_pct)))
    chunks, start = [], 0
    while start < len(tokens):
        end = min(start + target_tokens, len(tokens))
        chunks.append(enc.decode(tokens[start:end]))
        if end == len(tokens):
            break
        start += step
    return chunks


def child_pieces_for_section(sec: dict) -> List[dict]:
    """This section's children as {"text", "chunk_type"} dicts. A source module can pre-split a section into
    semantically real units (named subsections, tables, one sutra...) via ``sec["children"]``; blank texts are
    dropped and ``chunk_type`` defaults to "prose". Otherwise: fixed token windows with overlap."""
    custom = sec.get("children")
    if custom is not None:
        return [{"text": p["text"], "chunk_type": p.get("chunk_type", "prose")}
                for p in custom if p.get("text", "").strip()]
    return [{"text": t, "chunk_type": "prose"} for t in build_child_chunks(sec["text"])]


def contextual_header(filename: str, section: dict) -> str:
    """Prefix embedded with every child chunk. Section pages are 0-based internally; the header shows the
    1-based printed page numbers (this is what page citations are parsed from)."""
    return (f"[Source: {filename} | Section: {section['title']} | "
            f"Pages {section['start_page'] + 1}-{section['end_page'] + 1}]")


def write_chunks(cfg: Config, sources: Dict[str, dict], source_key: str, sections: List[dict]) -> Tuple[int, int]:
    """Write parent_chunk-N.json / child_chunk-parentN-chunkM.json for one source; returns (n_parents, n_children).

    Stale files from a previous run are deleted first, otherwise a run producing FEWER sections leaves old
    higher-numbered files behind and stage 1.9 reports them as orphans.
    """
    src = sources[source_key]
    out_dir = cfg.paths.output_root / source_key
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in list(out_dir.glob("parent_chunk-*.json")) + list(out_dir.glob("child_chunk-parent*-chunk*.json")):
        stale.unlink()

    n_parents = n_children = 0
    for p_idx, sec in enumerate(sections, start=1):
        parent = {
            "parent_id": f"{source_key}-p{p_idx}",
            "source": src["filename"],
            "source_key": source_key,
            "source_row_guid": src["row_guid"],   # becomes rowOwnerGUID in stage 1.2
            "title": sec["title"],
            "level": sec.get("level"),
            "start_page": sec["start_page"],
            "end_page": sec["end_page"],
            "block_type": sec.get("block_type", []),
            "text": sec["text"],
        }
        (out_dir / f"parent_chunk-{p_idx}.json").write_text(json.dumps(parent, ensure_ascii=False, indent=2), encoding="utf-8")
        n_parents += 1

        header = contextual_header(src["filename"], sec)
        for c_idx, piece in enumerate(child_pieces_for_section(sec), start=1):
            child = {
                "child_id": f"{source_key}-p{p_idx}-c{c_idx}",
                "parent_id": f"{source_key}-p{p_idx}",
                "source_key": source_key,
                "source_row_guid": src["row_guid"],
                "chunk_type": piece["chunk_type"],
                "text": f"{header}\n\n{piece['text']}",
                "token_count": token_len(piece["text"]),
            }
            (out_dir / f"child_chunk-parent{p_idx}-chunk{c_idx}.json").write_text(
                json.dumps(child, ensure_ascii=False, indent=2), encoding="utf-8")
            n_children += 1
    print(f"[{source_key}] wrote {n_parents} parent chunk(s), {n_children} child chunk(s) -> {out_dir}")
    return n_parents, n_children


def write_all_chunks(cfg: Config, sources: Dict[str, dict], sections_by_source: Dict[str, List[dict]]) -> Dict[str, Tuple[int, int]]:
    return {key: write_chunks(cfg, sources, key, sections_by_source[key]) for key in sources}


# ------------------------------------------------------------------------------------------- everything


@dataclass
class Result:
    cfg: Config
    sources: Dict[str, dict]
    counts: Dict[str, Tuple[int, int]]   # source_key -> (n_parents, n_children)

    @property
    def n_parents(self) -> int:
        return sum(p for p, _c in self.counts.values())

    @property
    def n_children(self) -> int:
        return sum(c for _p, c in self.counts.values())


def run_stage1_1(root=None, *, drive_files: Optional[List[dict]] = None) -> Result:
    """The whole of stage 1.1."""
    banner("Stage 1.1 -- extract & chunk")
    cfg = load_config(root)
    sources = build_sources(cfg, drive_files=drive_files)
    downloaded, fetch_info = download_sources(cfg, sources)
    write_source_manifests(cfg, sources, fetch_info)
    pages = extract_all_pages(cfg, sources, downloaded)
    sections = assemble_sections(cfg, sources, downloaded, pages, fetch_info)
    counts = write_all_chunks(cfg, sources, sections)
    result = Result(cfg, sources, counts)
    print(f"\nStage 1.1 done: {len(sources)} source(s), {result.n_parents} parent chunk(s), {result.n_children} child chunk(s).")
    return result
