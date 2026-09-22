"""LRM backend. GET /sources[?language=] -> list; GET /page?source=&page=&language= -> page JSON (blocks, word boxes, image path);
GET /files/<image path> -> page PNG from lrm/data/output."""
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reusable_code.clients import make_supabase_client  # noqa: E402

app = FastAPI(title="LRM API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
_sb = None
OUT = Path(__file__).resolve().parent.parent / "lrm" / "data" / "output"
OUT.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=OUT), name="files")


def sb():
    global _sb
    _sb = _sb or make_supabase_client()
    return _sb


@app.get("/sources")
def sources(language: str | None = None):
    q = sb().table("lrm_sources").select("rowGUID,source_key,language,title,rowJSON").order("orderInList")
    if language:
        q = q.eq("language", language)
    return [{"source_guid": r["rowGUID"], "source_key": r["source_key"], "language": r["language"], "title": r["title"],
             "page_count": r["rowJSON"].get("page_count"),
             "recognised_pages": r["rowJSON"].get("recognised_pages")} for r in q.execute().data]


@app.get("/page")
def page(source: str, page: int = 1, language: str = "fr"):
    r = (sb().table("lrm_pages").select("rowJSON").eq("source_key", source).eq("language", language)
         .eq("page_number", page).limit(1).execute().data)
    if not r:
        raise HTTPException(404, f"no page {page} for {source} [{language}]")
    return r[0]["rowJSON"]
