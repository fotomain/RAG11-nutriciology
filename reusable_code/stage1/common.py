"""Shared building blocks of the stage 1 pipeline (extract & chunk -> load -> verify).

Everything the three stages (and their notebooks) have in common lives here exactly once: project paths,
table names, the local chunk-file loaders, the Supabase row builders (so "what stage 1.2 writes" and
"what stage 1.9 expects" can never drift apart), NUL-byte sanitising, content fingerprints, and the retry
policy for database calls.
"""
import hashlib
import json
import re
import resource
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..crud_chunks_child import CHILD_TABLE
from ..crud_chunks_parent import PARENT_TABLE, deterministic_uuid
from ..retry import with_retry

SOURCES_TABLE = "rag11_data_sources"
EMBEDDING_DIM = 1024  # must match vector(...) in sql/create_sql_tables.sql and clients.EMBEDDING_MODEL

PARENT_FILE_RE = re.compile(r"^parent_chunk-(\d+)\.json$")
CHILD_FILE_RE = re.compile(r"^child_chunk-parent(\d+)-chunk(\d+)\.json$")

__all__ = [
    "SOURCES_TABLE", "PARENT_TABLE", "CHILD_TABLE", "EMBEDDING_DIM", "deterministic_uuid",
    "Paths", "get_paths", "LocalData", "load_local_data", "build_parent_row", "build_child_row",
    "strip_bad_unicode", "row_hash", "retry_db", "STATEMENT_TIMEOUT_CODE", "report_open_file_limit", "banner",
]


# --------------------------------------------------------------------------------------------- paths


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def input_root(self) -> Path:
        return self.root / "stage1_eda_input"

    @property
    def output_root(self) -> Path:
        return self.root / "stage1_eda_output"

    @property
    def sources_manifest_dir(self) -> Path:
        return self.output_root / "sources"

    @property
    def checkpoint_dir(self) -> Path:
        return self.output_root / "_checkpoints"


def get_paths(root=None) -> Paths:
    """Project paths; ``root`` defaults to the current directory (notebooks and the .command run from the repo root)."""
    return Paths(Path(root or ".").resolve())


def banner(text: str) -> None:
    print("\n" + "=" * 78 + f"\n  {text}\n" + "=" * 78)


def report_open_file_limit() -> int:
    """Print the process's open-file limit and what to do if it is low; returns the soft limit."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    print(f"This process's open-file limit: soft={soft}, hard={hard}")
    if soft < 2048:
        print("  -> LOW. If you see repeated '[Errno 35] Resource temporarily unavailable' during upserts, this is "
              "almost certainly why: run_stage1_all.command raises it for you; in Jupyter/PyCharm, run "
              "stage1_0_run_mac_settings.command once and fully restart the app.")
    return soft


# ------------------------------------------------------------------------------------ sanitising / hashing


def strip_bad_unicode(value):
    """Recursively strip NUL bytes out of every string nested in ``value`` (dicts/lists/strings).

    Postgres text/jsonb columns cannot store \\u0000 at all (APIError 22P05 'unsupported Unicode escape
    sequence'); source PDFs occasionally contain one from a bad font stream, and it rides along inside rowJSON.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: strip_bad_unicode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_bad_unicode(v) for v in value]
    return value


def row_hash(row: dict) -> str:
    """Fingerprint of everything that gets upserted for a row EXCEPT its embedding (a child's embedding is
    derived from the text inside rowJSON)."""
    payload = strip_bad_unicode({k: v for k, v in row.items() if k != "embedding"})
    return hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# Postgrest errors whose cause is the *data*, not the network: retrying just burns ~2 minutes of backoff
# before failing with the same error, so fail fast.
_NON_RETRYABLE_POSTGREST_CODES = {"22P05"}


STATEMENT_TIMEOUT_CODE = "57014"   # Postgres "canceling statement due to statement timeout"


def _retryable(exc: Exception, fail_fast: Tuple[str, ...] = ()) -> bool:
    code = getattr(exc, "code", None)
    if code in _NON_RETRYABLE_POSTGREST_CODES:
        print(f"[fatal] non-retryable Postgrest error ({exc}); not retrying -- this is a data problem, "
              f"not a network blip.")
        return False
    return code not in fail_fast   # fail_fast codes are handled by the caller (e.g. by splitting the batch)


def retry_db(fn, *args, fail_fast: Tuple[str, ...] = (), **kwargs):
    """Exponential-backoff retry (8 attempts) for flaky network calls. Data errors fail fast, and so do the
    Postgrest error codes in ``fail_fast`` (the caller has a better remedy than retrying the same call)."""
    return with_retry(fn, *args, max_attempts=8, base_delay=2.0,
                      is_retryable=lambda e: _retryable(e, fail_fast), **kwargs)


# ------------------------------------------------------------------------------------ local chunk files


def discover_source_keys(paths: Paths) -> List[str]:
    """Source keys that have a manifest row in stage1_eda_output/sources/ AND a chunk folder, sorted numerically.

    Keyed off the manifests (what stage 1.1 currently considers a source), so a stale ``sourceN`` folder left
    over from an earlier numbering is never loaded or verified as if it were current.
    """
    manifest_keys = {r["rowJSON"]["source_key"] for r in load_source_rows(paths)}
    on_disk = {p.name for p in paths.output_root.iterdir() if p.is_dir() and re.match(r"^source\d+$", p.name)}
    stale = sorted(on_disk - manifest_keys, key=lambda k: int(k[6:]))
    if stale:
        print(f"[note] ignoring chunk folder(s) with no manifest row (stale from an older run): {', '.join(stale)}")
    return sorted(manifest_keys & on_disk, key=lambda k: int(k[6:]))


def load_source_rows(paths: Paths) -> List[dict]:
    return [json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(paths.sources_manifest_dir.glob("source_row-*.json"), key=lambda f: int(f.stem.split("-")[1]))]


def load_parent_files(paths: Paths, source_key: str) -> List[Tuple[int, dict]]:
    """[(orderInList, parent_json), ...] sorted. N is parsed from the file NAME, not trusted from the JSON."""
    out = []
    for f in (paths.output_root / source_key).glob("parent_chunk-*.json"):
        m = PARENT_FILE_RE.match(f.name)
        if m:
            out.append((int(m.group(1)), json.loads(f.read_text(encoding="utf-8"))))
    out.sort(key=lambda t: t[0])
    return out


def load_child_files(paths: Paths, source_key: str) -> List[Tuple[int, int, dict]]:
    """[(parent_order, child_order, child_json), ...] sorted."""
    out = []
    for f in (paths.output_root / source_key).glob("child_chunk-*.json"):
        m = CHILD_FILE_RE.match(f.name)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), json.loads(f.read_text(encoding="utf-8"))))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


# ------------------------------------------------------------------------------------------ row builders


def _owner_guid(source_key: str, data: dict, guid_by_key: Dict[str, str]) -> str:
    owner = data.get("source_row_guid") or guid_by_key.get(source_key)
    if not owner:
        raise RuntimeError(
            f"No rag11_data_sources rowGUID found for '{source_key}' -- re-run stage 1.1 "
            "(stage1_1_eda_extract_and_chunk.ipynb): it writes source_row_guid into every parent/child chunk "
            "file and a source_row-N.json manifest per source."
        )
    return owner


def build_parent_row(source_key: str, order: int, data: dict, guid_by_key: Dict[str, str]) -> dict:
    return {
        "rowGUID": deterministic_uuid(f"parent:{data['parent_id']}"),
        "rowOwnerGUID": _owner_guid(source_key, data, guid_by_key),
        "rowParentGUID": None,
        "orderInList": order,
        "rowJSON": data,
    }


def build_child_row(source_key: str, order: int, data: dict, guid_by_key: Dict[str, str], embedding=None) -> dict:
    return {
        "rowGUID": deterministic_uuid(f"child:{data['child_id']}"),
        "rowOwnerGUID": _owner_guid(source_key, data, guid_by_key),
        "rowParentGUID": deterministic_uuid(f"parent:{data['parent_id']}"),
        "orderInList": order,
        "rowJSON": data,
        "embedding": embedding,
    }


@dataclass
class LocalData:
    """Everything stage 1.1 wrote to disk, in the shape stages 1.2 and 1.9 need."""
    paths: Paths
    source_keys: List[str]
    source_rows: List[dict]
    guid_by_key: Dict[str, str]
    parents_by_source: Dict[str, List[Tuple[int, dict]]]
    children_by_source: Dict[str, List[Tuple[int, int, dict]]]

    def parent_rows(self) -> List[dict]:
        return [build_parent_row(k, order, data, self.guid_by_key)
                for k in self.source_keys for order, data in self.parents_by_source[k]]

    def child_stubs(self) -> List[Tuple[str, int, dict]]:
        """[(source_key, orderInList, child_json), ...] in source/parent/chunk order."""
        return [(k, c_order, data) for k in self.source_keys
                for _p_order, c_order, data in self.children_by_source[k]]

    def child_rows(self) -> List[dict]:
        """Child rows WITHOUT embeddings (what stage 1.9 compares against)."""
        return [build_child_row(k, o, d, self.guid_by_key) for k, o, d in self.child_stubs()]

    def counts(self) -> str:
        return (f"{len(self.source_rows)} source row(s), {sum(len(v) for v in self.parents_by_source.values())} "
                f"parent row(s), {sum(len(v) for v in self.children_by_source.values())} child row(s)")


def load_local_data(paths: Paths, *, verbose: bool = True) -> LocalData:
    source_rows = load_source_rows(paths)
    if not source_rows:
        raise RuntimeError(f"No source manifest files found in {paths.sources_manifest_dir} -- run stage 1.1 first "
                           "(stage1_1_eda_extract_and_chunk.ipynb, or run_stage1_all.command).")
    source_keys = discover_source_keys(paths)
    parents = {k: load_parent_files(paths, k) for k in source_keys}
    children = {k: load_child_files(paths, k) for k in source_keys}
    if verbose:
        for k in source_keys:
            print(f"[{k}] {len(parents[k])} parent file(s), {len(children[k])} child file(s)")
    return LocalData(
        paths=paths, source_keys=source_keys, source_rows=source_rows,
        guid_by_key={r["rowJSON"]["source_key"]: r["rowGUID"] for r in source_rows},
        parents_by_source=parents, children_by_source=children,
    )
