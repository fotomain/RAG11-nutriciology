"""Offline tests for reusable_code.reasoning with fully faked Supabase/Voyage/Anthropic clients --
no network access or .env required. Run: .venv/bin/python test_reasoning.py"""
import sys
from types import SimpleNamespace

sys.path.insert(0, ".")

from reusable_code.clients import Clients  # noqa: E402
from reusable_code.reasoning import ask_with_reasoning  # noqa: E402
from reusable_code.reasoning.prompts import SELF_CHECK_SYSTEM_PROMPT  # noqa: E402

FAILURES = []


def check(label, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILURES.append(label)


def make_row(guid, text, cosine_distance, source_key="source1"):
    return {
        "rowGUID": guid, "rowParentGUID": "parent-1", "rowOwnerGUID": "owner-1", "orderInList": 0,
        "cosine_distance": cosine_distance, "rowJSON": {"text": text, "source_key": source_key},
    }


class FakeRPCResult:
    def __init__(self, data):
        self.data = data


class FakeRPCBuilder:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return FakeRPCResult(self._data)


class FakeSupabase:
    def __init__(self, rows):
        self._rows = rows
        self.rpc_calls = []

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return FakeRPCBuilder(self._rows[: params.get("match_count", len(self._rows))])


class FakeVoyage:
    def embed(self, texts, model, input_type):
        return SimpleNamespace(embeddings=[[0.1, 0.2, 0.3]])


class FakeAnthropicReasoning:
    """Routes strictly by system prompt: SELF_CHECK_SYSTEM_PROMPT calls consume the next verdict
    off `verdicts` (a JSON string each -- the last one repeats once exhausted, so a test doesn't
    need to supply one verdict per possible step); every other call (the draft-answer generation)
    gets `draft_text`."""

    def __init__(self, draft_text, verdicts):
        self._draft_text = draft_text
        self._verdicts = list(verdicts)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("system") == SELF_CHECK_SYSTEM_PROMPT:
            verdict = self._verdicts.pop(0) if len(self._verdicts) > 1 else self._verdicts[0]
            return SimpleNamespace(content=[
                SimpleNamespace(type="thinking", thinking="checking..."),
                SimpleNamespace(type="text", text=verdict),
            ])
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._draft_text)])


rows = [
    make_row("g1", "The Yoga-Sutra defines yoga as the cessation of the mind's fluctuations.", 0.1),
    make_row("g2", "Ahimsa means non-violence toward all beings.", 0.2),
]

# ---------------------------------------------------------------------------
# 1. First-try success: self-check says supported -> exactly one step
# ---------------------------------------------------------------------------
anth = FakeAnthropicReasoning(
    draft_text="Short answer: Yes\n\nAhimsa means non-violence.",
    verdicts=['{"supported": true, "unsupported_claims": [], "refine_query": null}'],
)
clients = Clients(supabase=FakeSupabase(rows), voyage=FakeVoyage(), anthropic=anth)
result = ask_with_reasoning("What does ahimsa mean?", use_hybrid=False, use_hyde=False, use_multi_query=False,
                             expand_to_parents=False, clients=clients)
check("first-try success: reasoning_used is True", result["reasoning_used"] is True)
check("first-try success: exactly 1 step taken", len(result["reasoning_steps"]) == 1)
check("first-try success: reasoning_verified is True", result["reasoning_verified"] is True)
check("first-try success: answer text passed through from ask_question", "non-violence" in result["answer"])
check("first-try success: chunks/context_block present on the result", result["chunks"] and result["context_block"])

# ---------------------------------------------------------------------------
# 2. Refine loop: unsupported on step 1 (with a refine_query), supported on step 2
# ---------------------------------------------------------------------------
anth2 = FakeAnthropicReasoning(
    draft_text="Short answer: Yes\n\nAhimsa means non-violence.",
    verdicts=[
        '{"supported": false, "unsupported_claims": ["x"], "refine_query": "ahimsa definition non-violence"}',
        '{"supported": true, "unsupported_claims": [], "refine_query": null}',
    ],
)
clients2 = Clients(supabase=FakeSupabase(rows), voyage=FakeVoyage(), anthropic=anth2)
result2 = ask_with_reasoning("What does ahimsa mean?", max_steps=4, use_hybrid=False, use_hyde=False,
                              use_multi_query=False, expand_to_parents=False, clients=clients2)
check("refine loop: took exactly 2 steps", len(result2["reasoning_steps"]) == 2)
check("refine loop: step 1 retrieval_query is the original question",
      result2["reasoning_steps"][0]["retrieval_query"] == "What does ahimsa mean?")
check("refine loop: step 2 retrieval_query is the refined query",
      result2["reasoning_steps"][1]["retrieval_query"] == "ahimsa definition non-violence")
check("refine loop: final reasoning_verified is True", result2["reasoning_verified"] is True)
check("refine loop: step 1 self_check recorded as unsupported",
      result2["reasoning_steps"][0]["self_check"]["supported"] is False)

# ---------------------------------------------------------------------------
# 3. Always unsupported -> stops at max_steps, never loops forever
# ---------------------------------------------------------------------------
anth3 = FakeAnthropicReasoning(
    draft_text="Short answer: Yes\n\nAhimsa means non-violence.",
    verdicts=['{"supported": false, "unsupported_claims": ["x"], "refine_query": "still refining"}'],
)
clients3 = Clients(supabase=FakeSupabase(rows), voyage=FakeVoyage(), anthropic=anth3)
result3 = ask_with_reasoning("What does ahimsa mean?", max_steps=3, use_hybrid=False, use_hyde=False,
                              use_multi_query=False, expand_to_parents=False, clients=clients3)
check("max-steps cap: stops at exactly max_steps (3)", len(result3["reasoning_steps"]) == 3)
check("max-steps cap: reasoning_verified is False (never resolved)", result3["reasoning_verified"] is False)

# ---------------------------------------------------------------------------
# 4. self_check=False -> single step, no self-check call at all
# ---------------------------------------------------------------------------
anth4 = FakeAnthropicReasoning(draft_text="Short answer: Yes\n\nAhimsa means non-violence.", verdicts=["{}"])
clients4 = Clients(supabase=FakeSupabase(rows), voyage=FakeVoyage(), anthropic=anth4)
result4 = ask_with_reasoning("What does ahimsa mean?", self_check=False, use_hybrid=False, use_hyde=False,
                              use_multi_query=False, expand_to_parents=False, clients=clients4)
check("self_check=False: exactly 1 step, no self_check key recorded",
      len(result4["reasoning_steps"]) == 1 and "self_check" not in result4["reasoning_steps"][0])
check("self_check=False: reasoning_verified is None", result4["reasoning_verified"] is None)
check("self_check=False: only the draft-generation call happened (no self-check call)", len(anth4.calls) == 1)

# ---------------------------------------------------------------------------
# 5. refine_query missing but supported=false -> stop anyway (nothing better to try)
# ---------------------------------------------------------------------------
anth5 = FakeAnthropicReasoning(
    draft_text="Short answer: Yes\n\nAhimsa means non-violence.",
    verdicts=['{"supported": false, "unsupported_claims": ["x"], "refine_query": null}'],
)
clients5 = Clients(supabase=FakeSupabase(rows), voyage=FakeVoyage(), anthropic=anth5)
result5 = ask_with_reasoning("What does ahimsa mean?", max_steps=4, use_hybrid=False, use_hyde=False,
                              use_multi_query=False, expand_to_parents=False, clients=clients5)
check("no refine_query offered: stops after 1 step instead of looping with a stale query",
      len(result5["reasoning_steps"]) == 1)

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All checks passed.")
    sys.exit(0)
