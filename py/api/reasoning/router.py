"""POST /ask -- question in, grounded answer out. Thin HTTP wrapper around
reusable_code.ask_question()/reusable_code.reasoning.ask_with_reasoning(); no retrieval or
generation logic lives here, only request/response shaping and resolving a source_key+language
pair (what a client naturally has) into the lrm_source_table.rowGUID ask_question() needs
(filter_owner)."""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from reusable_code import USE_REASONING, ask_question, get_clients, init_clients
from reusable_code.clients import make_supabase_client
from reusable_code.reasoning import ask_with_reasoning

router = APIRouter()

_sb = None


def sb():
    global _sb
    _sb = _sb or make_supabase_client()
    return _sb


def _clients():
    try:
        return get_clients()
    except RuntimeError:
        return init_clients()


def _resolve_owner(source_key: Optional[str], language: Optional[str]) -> Optional[str]:
    """A client naturally has (source_key, language) -- e.g. from GET /sources -- not the
    internal rowGUID ask_question()'s filter_owner needs. None/None means "search every source"."""
    if not source_key:
        return None
    q = sb().table("lrm_source_table").select("rowGUID").eq("source_key", source_key)
    if language:
        q = q.eq("language", language)
    rows = q.limit(1).execute().data
    if not rows:
        raise HTTPException(404, f"no source {source_key!r}" + (f" [{language}]" if language else ""))
    return rows[0]["rowGUID"]


class AskRequest(BaseModel):
    question: str
    source_key: Optional[str] = None  # restrict to one book; omit to search every uploaded source
    language: Optional[str] = None  # narrows source_key lookup when the same book has multiple languages
    answer_language: Optional[str] = None  # ISO code, e.g. "EN" -- language the answer itself is written in
    use_reasoning: Optional[bool] = None  # override USE_REASONING (.env default) for this request only


@router.post("/ask")
def ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(422, "question must not be empty")
    filter_owner = _resolve_owner(req.source_key, req.language)
    clients = _clients()
    use_reasoning = USE_REASONING if req.use_reasoning is None else req.use_reasoning

    if use_reasoning:
        result = ask_with_reasoning(
            req.question, filter_owner=filter_owner, answer_language=req.answer_language, clients=clients,
        )
    else:
        result = ask_question(
            req.question, filter_owner=filter_owner, answer_language=req.answer_language, clients=clients,
        )

    # chunks/context_block carry the full retrieved text -- useful for a notebook debugging retrieval,
    # noisy for an HTTP client that just wants the answer + which pages it came from.
    result.pop("chunks", None)
    result.pop("context_block", None)
    return result
