"""GET /sources[?language=] -> list; GET /page?source=&page=&language= -> page JSON (blocks, word
boxes, image path). The page-image viewer's data endpoints -- everything LRMPageDashboard (the
frontend) reads to list books and render a page. Reasoning/Q&A endpoints live in ../reasoning/
instead; this router only ever reads lrm_source_table/lrm_page_table, nothing calls an LLM here."""
from pathlib import Path

from fastapi import APIRouter, HTTPException

from reusable_code.clients import make_supabase_client

router = APIRouter()

# Where recognised page JSON + PNGs live on disk -- main.py mounts this at /files.
OUT = Path(__file__).resolve().parent.parent.parent / "lrm" / "eda1_extract" / "output"

_sb = None


def sb():
    global _sb
    _sb = _sb or make_supabase_client()
    return _sb


@router.get("/sources")
def sources(language: str | None = None):
    q = sb().table("lrm_source_table").select("rowGUID,source_key,language,title,rowJSON").order("orderInList")
    if language:
        q = q.eq("language", language)
    return [{"source_guid": r["rowGUID"], "source_key": r["source_key"], "language": r["language"], "title": r["title"],
             "page_count": r["rowJSON"].get("page_count"),
             "recognised_pages": r["rowJSON"].get("recognised_pages")} for r in q.execute().data]


@router.get("/page")
def page(source: str, page: int = 1, language: str = "fr"):
    r = (sb().table("lrm_page_table").select("rowJSON").eq("source_key", source).eq("language", language)
         .eq("page_number", page).limit(1).execute().data)
    if not r:
        raise HTTPException(404, f"no page {page} for {source} [{language}]")
    return r[0]["rowJSON"]
