"""Standalone unit tests for reusable_code, using fully faked
Supabase/Voyage/Anthropic clients -- no network access required. Run with:

    python3 test_reusable_code.py

This exercises the exact code that will import into stage2/stage3
notebooks, so a bug here is a bug there.
"""
import sys
from types import SimpleNamespace

sys.path.insert(0, ".")

from reusable_code.clients import Clients  # noqa: E402
from reusable_code.generation import ask_question, build_context_block  # noqa: E402
from reusable_code.retrieval import rerank_chunks, retrieve_chunks, update_rank_value  # noqa: E402

FAILURES = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def make_row(guid, text, cosine_distance, source_key="source1"):
    return {
        "rowGUID": guid,
        "rowParentGUID": "parent-1",
        "rowOwnerGUID": "owner-1",
        "orderInList": 0,
        "cosine_distance": cosine_distance,
        "rowJSON": {"text": text, "source_key": source_key},
    }


# ---------------------------------------------------------------------------
# Fake clients
# ---------------------------------------------------------------------------

class FakeRPCResult:
    def __init__(self, data):
        self.data = data


class FakeRPCBuilder:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return FakeRPCResult(self._data)


class FakeSupabaseTableRow:
    def __init__(self, data):
        self.data = data


class FakeSupabaseTableQuery:
    def __init__(self, store, table_name):
        self._store = store
        self._table_name = table_name
        self._filters = {}
        self._select_cols = None
        self._update_payload = None

    def select(self, *_cols):
        self._select_cols = _cols
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def single(self):
        return self

    def execute(self):
        rows = self._store[self._table_name]
        matches = [r for r in rows if all(r.get(k) == v for k, v in self._filters.items())]
        if self._update_payload is not None:
            for r in matches:
                r.update(self._update_payload)
            return FakeSupabaseTableRow({"status": "updated", "count": len(matches)})
        if not matches:
            raise RuntimeError("no matching row (fake supabase)")
        return FakeSupabaseTableRow(matches[0])


class FakeSupabase:
    def __init__(self, rpc_data, table_rows=None):
        self._rpc_data = rpc_data
        self._tables = table_rows or {}
        self.rpc_calls = []
        self.update_calls = []

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return FakeRPCBuilder(self._rpc_data[: params.get("match_count", len(self._rpc_data))])

    def table(self, name):
        return FakeSupabaseTableQuery(self._tables, name)


class FakeVoyage:
    def __init__(self, rerank_order):
        # rerank_order: list of (index_into_documents, relevance_score),
        # already sorted best-first, mimicking Voyage's real response shape.
        self._rerank_order = rerank_order
        self.embed_calls = []
        self.rerank_calls = []

    def embed(self, texts, model, input_type):
        self.embed_calls.append((texts, model, input_type))
        return SimpleNamespace(embeddings=[[0.1, 0.2, 0.3]])

    def rerank(self, query, documents, model, top_k, truncation=True):
        self.rerank_calls.append((query, documents, model, top_k))
        results = [
            SimpleNamespace(index=idx, document=documents[idx], relevance_score=score)
            for idx, score in self._rerank_order[:top_k]
        ]
        return SimpleNamespace(results=results)


class FakeAnthropicMessages:
    def __init__(self, answer_text):
        self._answer_text = answer_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._answer_text)])


class FakeAnthropic:
    def __init__(self, answer_text):
        self.messages = FakeAnthropicMessages(answer_text)


# ---------------------------------------------------------------------------
# retrieve_chunks
# ---------------------------------------------------------------------------

rows = [
    make_row("g1", "General macronutrient overview text about carbs, fat, protein.", 0.20),
    make_row("g2", "The RDA for protein is 0.8 g per kg of body weight per day.", 0.35),
    make_row("g3", "Fiber and digestion background text.", 0.25),
]
fake_supabase = FakeSupabase(rpc_data=rows)
fake_voyage = FakeVoyage(rerank_order=[(1, 0.95), (0, 0.40), (2, 0.10)])
fake_anthropic = FakeAnthropic(answer_text="Short answer: Yes\n\nExplanation using protein and RDA text.")
fake_clients = Clients(supabase=fake_supabase, voyage=fake_voyage, anthropic=fake_anthropic)

retrieved = retrieve_chunks("What is the RDA for protein?", match_count=3, clients=fake_clients)
check("retrieve_chunks returns all fake rows", len(retrieved) == 3)
check("retrieve_chunks passes match_count through to RPC", fake_supabase.rpc_calls[-1][1]["match_count"] == 3)

# ---------------------------------------------------------------------------
# rerank_chunks: the actually-relevant chunk (g2, initially rank 2) should
# move to rank 1 after reranking, mirroring the shared-conversation example.
# ---------------------------------------------------------------------------

reranked = rerank_chunks("What is the RDA for protein?", retrieved, top_n=3, clients=fake_clients)
check("rerank_chunks returns 3 rows", len(reranked) == 3)
check("rerank_chunks puts the truly relevant chunk (g2) first", reranked[0]["rowGUID"] == "g2")
check("rerank_chunks attaches rerank_score", reranked[0]["rerank_score"] == 0.95)
check("rerank_chunks attaches retrieval_rank (1-based pre-rerank position)", reranked[0]["retrieval_rank"] == 2)
check("rerank_chunks does not mutate the input list", retrieved[0]["rowGUID"] == "g1" and "rerank_score" not in retrieved[0])

# top_n narrower than the pool
top1 = rerank_chunks("q", retrieved, top_n=1, clients=fake_clients)
check("rerank_chunks respects top_n", len(top1) == 1 and top1[0]["rowGUID"] == "g2")

# empty input
check("rerank_chunks([]) returns []", rerank_chunks("q", [], clients=fake_clients) == [])

# ---------------------------------------------------------------------------
# build_context_block shows rerank_score when present, omits it otherwise
# ---------------------------------------------------------------------------

block_plain = build_context_block(retrieved)
block_reranked = build_context_block(reranked)
check("build_context_block omits relevance label pre-rerank", "relevance" not in block_plain)
check("build_context_block shows relevance label post-rerank", "relevance 0.95" in block_reranked)

# ---------------------------------------------------------------------------
# update_rank_value: manual override beats both rerank_score and cosine_distance
# ---------------------------------------------------------------------------

overridden = update_rank_value(reranked, row_guid="g3", new_value=0.99, reason="clinically important caveat")
check("update_rank_value returns same length", len(overridden) == 3)
check("update_rank_value moves manually-boosted chunk to the top", overridden[0]["rowGUID"] == "g3")
check("update_rank_value stores the reason", overridden[0]["manual_rank_reason"] == "clinically important caveat")
check("update_rank_value does not mutate its input", "manual_rank_score" not in reranked[2])

try:
    update_rank_value(reranked, row_guid="does-not-exist", new_value=1.0)
    check("update_rank_value raises ValueError for unknown rowGUID", False)
except ValueError:
    check("update_rank_value raises ValueError for unknown rowGUID", True)

# persist=True path -- should merge into the fake table's stored rowJSON
# without requiring any new column.
persist_store = {
    "rag11_chunks_child_table": [
        {"rowGUID": "g3", "rowJSON": {"text": "Fiber and digestion background text.", "source_key": "source1"}},
    ]
}
fake_supabase_persist = FakeSupabase(rpc_data=rows, table_rows=persist_store)
fake_clients_persist = Clients(supabase=fake_supabase_persist, voyage=fake_voyage, anthropic=fake_anthropic)
update_rank_value(reranked, row_guid="g3", new_value=0.77, persist=True, clients=fake_clients_persist)
persisted_row_json = persist_store["rag11_chunks_child_table"][0]["rowJSON"]
check("update_rank_value(persist=True) merges manual_rank_score into existing rowJSON",
      persisted_row_json.get("manual_rank_score") == 0.77)
check("update_rank_value(persist=True) leaves the original rowJSON keys intact",
      persisted_row_json.get("text") == "Fiber and digestion background text.")

# ---------------------------------------------------------------------------
# ask_question: use_rerank is optional and defaults to False
# ---------------------------------------------------------------------------

result_plain = ask_question("What is the RDA for protein?", match_count=3, clients=fake_clients)
check("ask_question() works with no use_rerank arg at all", result_plain["used_rerank"] is False)
check("ask_question() (no rerank) uses match_count chunks directly", result_plain["chunks_used"] == 3)
check("ask_question() (no rerank) candidates_considered == chunks_used", result_plain["candidates_considered"] == 3)
check("ask_question() rerank_model is None when unused", result_plain["rerank_model"] is None)

fake_supabase2 = FakeSupabase(rpc_data=rows)
fake_clients2 = Clients(supabase=fake_supabase2, voyage=fake_voyage, anthropic=fake_anthropic)
result_rerank = ask_question(
    "What is the RDA for protein?", match_count=2, use_rerank=True, clients=fake_clients2
)
check("ask_question(use_rerank=True) marks used_rerank", result_rerank["used_rerank"] is True)
check("ask_question(use_rerank=True) returns rerank_top_n (default match_count) chunks",
      result_rerank["chunks_used"] == 2)
check("ask_question(use_rerank=True) requested a wider candidate pool from retrieve_chunks",
      fake_supabase2.rpc_calls[-1][1]["match_count"] >= 15)  # RERANK_MIN_POOL
check("ask_question(use_rerank=True) candidates_considered reflects what came back",
      result_rerank["candidates_considered"] == len(rows))  # fake dataset only has 3 rows total
check("ask_question(use_rerank=True) records the rerank model", result_rerank["rerank_model"] == "rerank-2")
check("ask_question(use_rerank=True) parses the Short answer line",
      result_rerank["short_answer"] == "Yes")

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(" -", f)
    sys.exit(1)
else:
    print("All checks passed.")
