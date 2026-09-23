"""LRM backend -- app assembly only. GET /sources, GET /page, GET /files/... (the page-image
viewer's data, see sources/router.py); POST /ask (reasoning Q&A, see reasoning/router.py). No
route logic lives in this file; it only wires the two routers together and mounts static files."""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from .reasoning import router as reasoning_router  # noqa: E402
from .sources import OUT, router as sources_router  # noqa: E402

app = FastAPI(title="LRM API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])

OUT.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=OUT), name="files")

app.include_router(sources_router)
app.include_router(reasoning_router)
