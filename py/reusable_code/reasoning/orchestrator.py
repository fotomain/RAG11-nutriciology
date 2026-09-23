"""Multi-step reasoning on top of plain ask_question(): draft -> self-check the draft's claims
against the excerpts it actually retrieved -> if unsupported, retrieve again with a refined query
and redraft -> repeat up to REASONING_MAX_STEPS times.

ask_question() (generation.py) is a single retrieve-then-generate call -- excellent at "does the
answer follow from what got retrieved", but blind to "did we retrieve the right thing at all". This
module adds that second check on top, using Claude's extended thinking for the verification step
(the actual answer generation is unaffected -- it's still plain ask_question() underneath, so
every USE_HYBRID_SEARCH/USE_PARENT_CHUNK_EXPANSION/etc. technique already in play keeps working
exactly as before; reasoning only decides whether to loop back and try again with a better query).

Off by default (USE_REASONING=False in .env, see config.py) -- slower and more expensive than a
single ask_question() call, so it's opt-in, the same way use_rerank defaults to False in
ask_question() itself.
"""
import json
import re
from typing import Optional

from ..clients import Clients, get_clients
from ..config import (
    REASONING_MAX_STEPS,
    REASONING_MAX_THINKING_TOKENS,
    REASONING_MODEL,
    REASONING_SELF_CHECK,
)
from ..ask.generation import ask_question
from ..retry import with_retry
from .prompts import SELF_CHECK_SYSTEM_PROMPT

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _self_check(
    question: str,
    context_block: str,
    draft_answer: str,
    *,
    reasoning_model: str,
    max_thinking_tokens: int,
    clients: Clients,
) -> dict:
    """One extended-thinking call: does ``draft_answer`` follow only from ``context_block``?
    Returns {"supported": bool, "unsupported_claims": list, "refine_query": str | None}. Fails
    open (treats a malformed/missing response as "supported") rather than looping forever on a
    parsing problem -- a wrong verdict here costs one wasted step at worst, not an infinite loop."""
    user_message = f"Question: {question}\n\nExcerpts:\n{context_block}\n\nDraft answer:\n{draft_answer}"
    resp = with_retry(
        lambda: clients.anthropic.messages.create(
            model=reasoning_model,
            max_tokens=max_thinking_tokens + 1024,
            thinking={"type": "enabled", "budget_tokens": max_thinking_tokens},
            system=SELF_CHECK_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        print("  [warn] self-check response had no parseable JSON verdict -- treating as supported")
        return {"supported": True, "unsupported_claims": [], "refine_query": None}
    try:
        verdict = json.loads(match.group(0))
    except json.JSONDecodeError:
        print("  [warn] self-check verdict wasn't valid JSON -- treating as supported")
        return {"supported": True, "unsupported_claims": [], "refine_query": None}
    return {
        "supported": bool(verdict.get("supported", True)),
        "unsupported_claims": verdict.get("unsupported_claims") or [],
        "refine_query": verdict.get("refine_query") or None,
    }


def ask_with_reasoning(
    question: str,
    *,
    max_steps: int = REASONING_MAX_STEPS,
    self_check: bool = REASONING_SELF_CHECK,
    reasoning_model: str = REASONING_MODEL,
    max_thinking_tokens: int = REASONING_MAX_THINKING_TOKENS,
    filter_owner: Optional[str] = None,
    clients: Optional[Clients] = None,
    **ask_question_kwargs,
) -> dict:
    """Like ``ask_question()``, but drafts, self-checks the draft against its own retrieved
    excerpts, and -- if the check finds unsupported claims -- retrieves again with a refined
    query and redrafts, up to ``max_steps`` times total. Every ``ask_question()`` keyword
    (``use_hybrid``, ``use_rerank``, ``answer_language``, ``system_prompt``, ...) is accepted and
    passed straight through unchanged on every step; only the retrieval *query* is refined between
    steps, never the retrieval technique.

    Returns the same dict ``ask_question()`` does, plus:
        reasoning_used       -- always True (so a caller can tell reasoning ran vs. plain ask_question())
        reasoning_steps      -- one entry per step: {step, retrieval_query, chunks_used, self_check}
        reasoning_verified   -- the final step's self-check "supported" value, or None if self_check=False
    """
    clients = clients or get_clients()
    retrieval_query = question
    steps = []
    result = None

    for step in range(1, max_steps + 1):
        result = ask_question(
            question,
            retrieval_query=retrieval_query,
            filter_owner=filter_owner,
            clients=clients,
            **ask_question_kwargs,
        )
        step_record = {"step": step, "retrieval_query": retrieval_query, "chunks_used": result["chunks_used"]}
        steps.append(step_record)

        if not self_check:
            break

        verdict = _self_check(
            question,
            result["context_block"],
            result["answer"],
            reasoning_model=reasoning_model,
            max_thinking_tokens=max_thinking_tokens,
            clients=clients,
        )
        step_record["self_check"] = verdict

        if verdict["supported"] or not verdict["refine_query"] or step == max_steps:
            break
        retrieval_query = verdict["refine_query"]

    result["reasoning_used"] = True
    result["reasoning_steps"] = steps
    result["reasoning_verified"] = steps[-1]["self_check"]["supported"] if self_check else None
    return result
