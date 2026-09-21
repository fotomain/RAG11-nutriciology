"""Standalone unit tests for reusable_code, using fully faked
Supabase/Voyage/Anthropic clients -- no network access required. Run with:

    python3 test_reusable_code.py

This exercises the exact code that will import into stage2/stage3
notebooks, so a bug here is a bug there.
"""
import inspect
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, ".")

from reusable_code import config as config_module  # noqa: E402
from reusable_code.clients import Clients  # noqa: E402
from reusable_code.env import optional_env_bool  # noqa: E402
from reusable_code.generation import SYSTEM_PROMPT as SYSTEM_PROMPT_DEFAULT  # noqa: E402
from reusable_code.generation import ask_question, build_context_block  # noqa: E402
from reusable_code.hybrid_search import (  # noqa: E402
    hybrid_search,
    reciprocal_rank_fusion,
    retrieve_chunks_keyword,
)
from reusable_code.hypothetical_document_embedding import (  # noqa: E402
    embed_hypothetical_document,
    generate_hypothetical_document,
    retrieve_chunks_hyde,
)
from reusable_code.multi_query_question_splitting import (  # noqa: E402
    retrieve_chunks_multi_query,
    split_into_subquestions,
)
from reusable_code.parent_chunk_expansion import (  # noqa: E402
    build_expanded_context_block,
    expand_to_parent_chunks,
    page_numbers_for_expanded_chunk,
)
from reusable_code.rerunk_code import rerank_chunks, update_rank_value  # noqa: E402
from reusable_code.retrieval import (  # noqa: E402
    page_numbers_for_chunk,
    retrieve_chunks,
)

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


def make_row_kw(guid, text, text_rank, source_key="source1"):
    return {
        "rowGUID": guid,
        "rowParentGUID": "parent-1",
        "rowOwnerGUID": "owner-1",
        "orderInList": 0,
        "text_rank": text_rank,
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
        self._single = False

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
        self._single = True
        return self

    def execute(self):
        rows = self._store[self._table_name]
        matches = [r for r in rows if all(r.get(k) == v for k, v in self._filters.items())]
        if self._update_payload is not None:
            for r in matches:
                r.update(self._update_payload)
            return FakeSupabaseTableRow({"status": "updated", "count": len(matches)})
        if self._single:
            if not matches:
                raise RuntimeError("no matching row (fake supabase)")
            return FakeSupabaseTableRow(matches[0])
        # Plain (non-.single()) select -- e.g. crud_chunks_parent.read_parent_row()'s
        # `.select("*").eq("rowGUID", row_guid).execute()`, which expects
        # `resp.data` to be a *list* (possibly empty, not an error).
        return FakeSupabaseTableRow(matches)


class FakeSupabase:
    def __init__(self, rpc_data, table_rows=None):
        # rpc_data may be a plain list (all calls, of any RPC name, get the
        # same data -- the original shape this fake supported) or a dict of
        # {rpc_name: data} for tests that need e.g. match_rag11_child_chunks
        # and match_rag11_child_chunks_keyword to return different rows.
        self._rpc_data = rpc_data if isinstance(rpc_data, dict) else {"match_rag11_child_chunks": rpc_data}
        self._tables = table_rows or {}
        self.rpc_calls = []
        self.update_calls = []

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        data = self._rpc_data.get(name, [])
        return FakeRPCBuilder(data[: params.get("match_count", len(data))])

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


class FakeAnthropicMessagesRouted:
    """Like FakeAnthropicMessages, but returns a different canned response
    depending on which system prompt a call used -- needed for multi-query
    tests, where one ask_question() call makes two different kinds of
    Anthropic calls (the question-splitting call, then the final generation
    call) against the same fake client."""

    def __init__(self, default_text, routes=None):
        self._default_text = default_text
        self._routes = routes or []  # list of (substring_in_system_prompt, response_text)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        system = kwargs.get("system", "")
        for marker, text in self._routes:
            if marker in system:
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._default_text)])


class FakeAnthropicRouted:
    def __init__(self, default_text, routes=None):
        self.messages = FakeAnthropicMessagesRouted(default_text, routes)


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
# reciprocal_rank_fusion: merges two independently-ranked lists. g2 is the
# chunk with the exact answer -- ranked #2 by dense search but #2 by
# keyword search too (present in both), while g4 is a keyword-only hit
# (an exact term dense search never surfaced at all) and g1 is a
# dense-only hit -- mirroring the "chunk A was #1 in vector, #3 in
# keyword" fusion scenario hybrid search exists for.
# ---------------------------------------------------------------------------

dense_ranked = [rows[0], rows[1], rows[2]]  # g1, g2, g3 -- dense ranks 1, 2, 3
g4 = make_row_kw("g4", "Exact keyword match text only a lexical search would surface.", 0.9)
keyword_ranked = [g4, rows[1], rows[2]]  # g4, g2, g3 -- keyword ranks 1, 2, 3 (g1 absent)

fused = reciprocal_rank_fusion({"dense": dense_ranked, "keyword": keyword_ranked})
check("reciprocal_rank_fusion returns every distinct chunk across both lists", len(fused) == 4)
fused_by_guid = {row["rowGUID"]: row for row in fused}
check("reciprocal_rank_fusion ranks the chunk present in both lists first", fused[0]["rowGUID"] == "g2")
check("reciprocal_rank_fusion records per-list ranks on the fused chunk",
      fused_by_guid["g2"]["dense_rank"] == 2 and fused_by_guid["g2"]["keyword_rank"] == 2)
check("reciprocal_rank_fusion marks a dense-only chunk's keyword_rank as None",
      fused_by_guid["g1"]["dense_rank"] == 1 and fused_by_guid["g1"]["keyword_rank"] is None)
check("reciprocal_rank_fusion still surfaces a keyword-only chunk (dense never saw it)",
      fused_by_guid["g4"]["dense_rank"] is None and fused_by_guid["g4"]["keyword_rank"] == 1)
check("reciprocal_rank_fusion sorts by rrf_score descending",
      all(fused[i]["rrf_score"] >= fused[i + 1]["rrf_score"] for i in range(len(fused) - 1)))

# ---------------------------------------------------------------------------
# retrieve_chunks_keyword: hits the keyword RPC, not the dense one
# ---------------------------------------------------------------------------

fake_supabase_hybrid = FakeSupabase(rpc_data={
    "match_rag11_child_chunks": dense_ranked,
    "match_rag11_child_chunks_keyword": keyword_ranked,
})
fake_clients_hybrid = Clients(supabase=fake_supabase_hybrid, voyage=fake_voyage, anthropic=fake_anthropic)

kw_results = retrieve_chunks_keyword("What is the RDA for protein?", match_count=3, clients=fake_clients_hybrid)
check("retrieve_chunks_keyword returns the keyword-ranked rows", [r["rowGUID"] for r in kw_results] == ["g4", "g2", "g3"])
check("retrieve_chunks_keyword calls the keyword RPC, not the dense one",
      fake_supabase_hybrid.rpc_calls[-1][0] == "match_rag11_child_chunks_keyword")

# ---------------------------------------------------------------------------
# hybrid_search: runs both searches and returns the fused, trimmed list
# ---------------------------------------------------------------------------

fake_supabase_hybrid2 = FakeSupabase(rpc_data={
    "match_rag11_child_chunks": dense_ranked,
    "match_rag11_child_chunks_keyword": keyword_ranked,
})
fake_clients_hybrid2 = Clients(supabase=fake_supabase_hybrid2, voyage=fake_voyage, anthropic=fake_anthropic)

hybrid_results = hybrid_search("What is the RDA for protein?", match_count=2, clients=fake_clients_hybrid2)
check("hybrid_search trims the fused list down to match_count", len(hybrid_results) == 2)
check("hybrid_search's top result is the chunk both methods agree on", hybrid_results[0]["rowGUID"] == "g2")
check("hybrid_search over-fetches a wider pool per method than match_count",
      all(call[1]["match_count"] >= 15 for call in fake_supabase_hybrid2.rpc_calls))  # HYBRID_MIN_POOL

# ---------------------------------------------------------------------------
# HyDE (hypothetical document embeddings): generate_hypothetical_document /
# embed_hypothetical_document / retrieve_chunks_hyde
# ---------------------------------------------------------------------------

fake_supabase_hyde = FakeSupabase(rpc_data=rows)
fake_clients_hyde = Clients(supabase=fake_supabase_hyde, voyage=fake_voyage, anthropic=fake_anthropic)

hyde_doc = generate_hypothetical_document("What is the RDA for protein?", clients=fake_clients_hyde)
check("generate_hypothetical_document returns Claude's drafted text",
      hyde_doc == fake_anthropic.messages._answer_text)

hyde_embedding = embed_hypothetical_document(hyde_doc, clients=fake_clients_hyde)
check("embed_hypothetical_document returns an embedding vector", hyde_embedding == [0.1, 0.2, 0.3])
check("embed_hypothetical_document uses input_type='document' (matches how child chunks were embedded)",
      fake_voyage.embed_calls[-1][2] == "document")

hyde_rows, hyde_text = retrieve_chunks_hyde(
    "What is the RDA for protein?", match_count=3, return_hypothetical_document=True, clients=fake_clients_hyde
)
check("retrieve_chunks_hyde returns the dense RPC rows", len(hyde_rows) == 3)
check("retrieve_chunks_hyde also returns the hypothetical document used to retrieve them", hyde_text == hyde_doc)
check("retrieve_chunks_hyde calls the same dense RPC retrieve_chunks() uses (no schema change needed)",
      fake_supabase_hyde.rpc_calls[-1][0] == "match_rag11_child_chunks")
check("retrieve_chunks_hyde embeds the hypothetical document, not the raw question",
      fake_voyage.embed_calls[-1][0] == [hyde_doc] and fake_voyage.embed_calls[-1][2] == "document")

check("retrieve_chunks_hyde without return_hypothetical_document returns a plain row list",
      retrieve_chunks_hyde("What is the RDA for protein?", match_count=3, clients=fake_clients_hyde) == hyde_rows)

# ---------------------------------------------------------------------------
# Multi-query / question splitting: split_into_subquestions /
# retrieve_chunks_multi_query
# ---------------------------------------------------------------------------

FIBER_COMPARISON_Q = "How does soluble fiber's effect on LDL cholesterol differ from insoluble fiber's effect?"
_SPLIT_MARKER = "split nutrition questions"  # unique substring of MULTI_QUERY_SYSTEM_PROMPT

fake_anthropic_split = FakeAnthropicRouted(
    default_text="Short answer: Yes\n\nExplanation.",
    routes=[(_SPLIT_MARKER,
             "SUBQ: What does soluble fiber do to LDL cholesterol?\n"
             "SUBQ: What does insoluble fiber do to LDL cholesterol?")],
)
fake_clients_split = Clients(supabase=fake_supabase, voyage=fake_voyage, anthropic=fake_anthropic_split)

subqs = split_into_subquestions(FIBER_COMPARISON_Q, clients=fake_clients_split)
check("split_into_subquestions splits a comparison question into 2 sub-questions", len(subqs) == 2)
check("split_into_subquestions parses each SUBQ: line",
      subqs == [
          "What does soluble fiber do to LDL cholesterol?",
          "What does insoluble fiber do to LDL cholesterol?",
      ])

fake_anthropic_nosplit = FakeAnthropicRouted(
    default_text="Short answer: Yes\n\nExplanation.",
    routes=[(_SPLIT_MARKER, "SUBQ: Is vitamin C water-soluble?")],
)
fake_clients_nosplit = Clients(supabase=fake_supabase, voyage=fake_voyage, anthropic=fake_anthropic_nosplit)
atomic_subqs = split_into_subquestions("Is vitamin C water-soluble?", clients=fake_clients_nosplit)
check("split_into_subquestions leaves an atomic question as a single-element list",
      atomic_subqs == ["Is vitamin C water-soluble?"])

fake_anthropic_garbage = FakeAnthropicRouted(
    default_text="Short answer: Yes\n\nExplanation.",
    routes=[(_SPLIT_MARKER, "I cannot help with that.")],
)
fake_clients_garbage = Clients(supabase=fake_supabase, voyage=fake_voyage, anthropic=fake_anthropic_garbage)
fallback_subqs = split_into_subquestions("Some question?", clients=fake_clients_garbage)
check("split_into_subquestions falls back to [question] when the response has no SUBQ: lines",
      fallback_subqs == ["Some question?"])


def fake_retrieve_fn(q, match_count, filter_owner=None, clients=None):
    """Stands in for retrieve_chunks()/hybrid_search(): returns different
    rows depending on which sub-question was searched, so fusion has
    something real to merge."""
    if "soluble" in q and "insoluble" not in q:
        return [rows[0], rows[1]]  # g1, g2
    return [rows[1], rows[2]]      # g2, g3


mq_rows, mq_subqs = retrieve_chunks_multi_query(
    FIBER_COMPARISON_Q, match_count=3, retrieve_fn=fake_retrieve_fn,
    return_subquestions=True, clients=fake_clients_split,
)
check("retrieve_chunks_multi_query returns the sub-questions it searched", len(mq_subqs) == 2)
check("retrieve_chunks_multi_query fuses per-sub-question results, chunk seen by both ranks first",
      mq_rows[0]["rowGUID"] == "g2")
check("retrieve_chunks_multi_query surfaces a chunk only one sub-question's search returned",
      {"g1", "g2", "g3"} == {r["rowGUID"] for r in mq_rows})
check("retrieve_chunks_multi_query without return_subquestions returns a plain row list",
      isinstance(
          retrieve_chunks_multi_query("Some question?", retrieve_fn=fake_retrieve_fn, clients=fake_clients_nosplit),
          list,
      ))

# ---------------------------------------------------------------------------
# build_context_block shows rerank_score when present, omits it otherwise
# ---------------------------------------------------------------------------

block_plain = build_context_block(retrieved)
block_reranked = build_context_block(reranked)
check("build_context_block omits relevance label pre-rerank", "relevance" not in block_plain)
check("build_context_block shows relevance label post-rerank", "relevance 0.95" in block_reranked)

# ---------------------------------------------------------------------------
# expand_to_parent_chunks / build_expanded_context_block /
# page_numbers_for_expanded_chunk -- parent-chunk expansion ("small-to-big")
# ---------------------------------------------------------------------------

parent_fiber = {
    "rowGUID": "parent-1",
    "rowOwnerGUID": "owner-1",
    "rowParentGUID": None,
    "orderInList": 0,
    "rowJSON": {
        "parent_id": "p1",
        "source_key": "source1",
        "title": "Fiber and Cholesterol",
        "start_page": 40,
        "end_page": 42,
        "text": (
            "Soluble fiber binds bile acids in the gut, which forces the liver "
            "to pull more LDL cholesterol from the blood to make more bile "
            "acids. Insoluble fiber, by contrast, does not bind bile acids "
            "and has little effect on LDL cholesterol; instead it adds bulk "
            "to stool and speeds transit time through the gut."
        ),
    },
}
fake_supabase_expand = FakeSupabase(rpc_data=rows, table_rows={"rag11_chunks_parent_table": [parent_fiber]})
fake_clients_expand = Clients(supabase=fake_supabase_expand, voyage=fake_voyage, anthropic=fake_anthropic)

# g1 and g2 (from `rows` above) both carry rowParentGUID == "parent-1" --
# they should collapse into ONE expanded row.
expanded = expand_to_parent_chunks([rows[0], rows[1]], clients=fake_clients_expand)
check("expand_to_parent_chunks dedups children sharing one parent", len(expanded) == 1)
check("expand_to_parent_chunks swaps in the parent's text",
      "insoluble fiber" in expanded[0]["rowJSON"]["text"].lower())
check("expand_to_parent_chunks keeps the best (first) child's rowGUID", expanded[0]["rowGUID"] == "g1")
check("expand_to_parent_chunks records every matched child",
      [r["rowGUID"] for r in expanded[0]["matched_children"]] == ["g1", "g2"])
check("expand_to_parent_chunks marks expanded_from_parent True", expanded[0]["expanded_from_parent"] is True)
check("expand_to_parent_chunks records the parent's own rowGUID",
      expanded[0]["parent_row_guid"] == "parent-1")
check("expand_to_parent_chunks does not mutate its input", "expanded_from_parent" not in rows[0])

short_expanded = expand_to_parent_chunks([rows[0]], max_parent_chars=20, clients=fake_clients_expand)
check("expand_to_parent_chunks truncates long parent text when max_parent_chars is set",
      short_expanded[0]["rowJSON"]["text"].startswith(parent_fiber["rowJSON"]["text"][:20].rstrip())
      and "truncated" in short_expanded[0]["rowJSON"]["text"])

orphan_child = make_row("g5", "An orphaned child chunk.", 0.5)
orphan_child["rowParentGUID"] = "missing-parent"
orphan_expanded = expand_to_parent_chunks([orphan_child], clients=fake_clients_expand)
check("expand_to_parent_chunks keeps the child chunk as-is when its parent is missing",
      orphan_expanded[0]["rowJSON"]["text"] == "An orphaned child chunk.")
check("expand_to_parent_chunks marks expanded_from_parent False when the parent is missing",
      orphan_expanded[0]["expanded_from_parent"] is False)

check("expand_to_parent_chunks([]) returns []", expand_to_parent_chunks([], clients=fake_clients_expand) == [])

expanded_block = build_expanded_context_block(expanded)
check("build_expanded_context_block shows the parent's title", "Fiber and Cholesterol" in expanded_block)
check("build_expanded_context_block shows how many child chunks it stands in for",
      "expanded from 2 matched chunks" in expanded_block)
check("build_expanded_context_block behaves like build_context_block for a plain (non-expanded) row",
      build_expanded_context_block([rows[0]]) == build_context_block([rows[0]]))

check("page_numbers_for_expanded_chunk converts a parent's 0-based start_page/end_page to 1-based pages",
      page_numbers_for_expanded_chunk(expanded[0]) == [41, 42, 43])
check("page_numbers_for_expanded_chunk falls back to the child text header otherwise",
      page_numbers_for_expanded_chunk(rows[0]) == page_numbers_for_chunk(rows[0]))

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

result_plain = ask_question(
    "What is the RDA for protein?", match_count=3, clients=fake_clients,
    use_hybrid=False, use_hyde=False, use_multi_query=False, expand_to_parents=False,
)
check("ask_question() works with no use_rerank arg at all", result_plain["used_rerank"] is False)
check("ask_question() (no rerank) uses match_count chunks directly", result_plain["chunks_used"] == 3)
check("ask_question() (no rerank) candidates_considered == chunks_used", result_plain["candidates_considered"] == 3)
check("ask_question() rerank_model is None when unused", result_plain["rerank_model"] is None)

fake_supabase2 = FakeSupabase(rpc_data=rows)
fake_clients2 = Clients(supabase=fake_supabase2, voyage=fake_voyage, anthropic=fake_anthropic)
result_rerank = ask_question(
    "What is the RDA for protein?", match_count=2, use_rerank=True, clients=fake_clients2,
    use_hybrid=False, use_hyde=False, use_multi_query=False, expand_to_parents=False,
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

# ---------------------------------------------------------------------------
# ask_question: use_hybrid is optional, defaults to False, and composes
# with use_rerank (hybrid picks candidates, rerank re-scores them)
# ---------------------------------------------------------------------------

check("ask_question() (no use_hybrid arg) marks used_hybrid False", result_plain["used_hybrid"] is False)

fake_supabase_hybrid_ask = FakeSupabase(rpc_data={
    "match_rag11_child_chunks": dense_ranked,
    "match_rag11_child_chunks_keyword": keyword_ranked,
})
fake_clients_hybrid_ask = Clients(supabase=fake_supabase_hybrid_ask, voyage=fake_voyage, anthropic=fake_anthropic)

result_hybrid = ask_question(
    "What is the RDA for protein?", match_count=2, use_hybrid=True, clients=fake_clients_hybrid_ask,
    use_hyde=False, use_multi_query=False, expand_to_parents=False,
)
check("ask_question(use_hybrid=True) marks used_hybrid", result_hybrid["used_hybrid"] is True)
check("ask_question(use_hybrid=True) uses the fused top result",
      result_hybrid["chunks_used"] == 2)
check("ask_question(use_hybrid=True) queried both the dense and keyword RPCs",
      {"match_rag11_child_chunks", "match_rag11_child_chunks_keyword"}
      == {name for name, _ in fake_supabase_hybrid_ask.rpc_calls})

fake_supabase_hybrid_rerank = FakeSupabase(rpc_data={
    "match_rag11_child_chunks": dense_ranked,
    "match_rag11_child_chunks_keyword": keyword_ranked,
})
fake_clients_hybrid_rerank = Clients(supabase=fake_supabase_hybrid_rerank, voyage=fake_voyage, anthropic=fake_anthropic)
result_hybrid_rerank = ask_question(
    "What is the RDA for protein?", match_count=2,
    use_hybrid=True, use_rerank=True, clients=fake_clients_hybrid_rerank,
    use_hyde=False, use_multi_query=False, expand_to_parents=False,
)
check("ask_question(use_hybrid=True, use_rerank=True) marks both flags",
      result_hybrid_rerank["used_hybrid"] is True and result_hybrid_rerank["used_rerank"] is True)
check("ask_question(use_hybrid=True, use_rerank=True) still queried both hybrid RPCs before reranking",
      {"match_rag11_child_chunks", "match_rag11_child_chunks_keyword"}
      == {name for name, _ in fake_supabase_hybrid_rerank.rpc_calls})

# ---------------------------------------------------------------------------
# ask_question: use_hyde is optional and defaults to False
# ---------------------------------------------------------------------------

check("ask_question() (no use_hyde arg) marks used_hyde False and hypothetical_document None",
      result_plain["used_hyde"] is False and result_plain["hypothetical_document"] is None)

fake_supabase_hyde_ask = FakeSupabase(rpc_data=rows)
fake_clients_hyde_ask = Clients(supabase=fake_supabase_hyde_ask, voyage=fake_voyage, anthropic=fake_anthropic)
result_hyde = ask_question(
    "What is the RDA for protein?", match_count=3, use_hyde=True, clients=fake_clients_hyde_ask,
    use_hybrid=False, use_multi_query=False, expand_to_parents=False,
)
check("ask_question(use_hyde=True) marks used_hyde", result_hyde["used_hyde"] is True)
check("ask_question(use_hyde=True) returns the hypothetical document used for retrieval",
      result_hyde["hypothetical_document"] == fake_anthropic.messages._answer_text)
check("ask_question(use_hyde=True) still uses match_count chunks", result_hyde["chunks_used"] == 3)
check("ask_question(use_hyde=True) queried the dense RPC with an embedding derived from the hypothetical doc",
      fake_supabase_hyde_ask.rpc_calls[-1][0] == "match_rag11_child_chunks")

# ---------------------------------------------------------------------------
# ask_question: use_multi_query is optional, defaults to False, takes
# priority over use_hyde (ignored), and composes with use_hybrid (each
# sub-question is itself searched with hybrid_search()).
# ---------------------------------------------------------------------------

check("ask_question() (no use_multi_query arg) marks used_multi_query False and subquestions None",
      result_plain["used_multi_query"] is False and result_plain["subquestions"] is None)

MULTI_Q = "What is the RDA for protein, and how much per kg is recommended?"
mq_split_routes = [(_SPLIT_MARKER,
                     "SUBQ: What is the RDA for protein?\nSUBQ: How much protein per kg is recommended?")]

fake_supabase_mq = FakeSupabase(rpc_data=rows)
fake_anthropic_mq = FakeAnthropicRouted(
    default_text="Short answer: Yes\n\nExplanation using protein and RDA text.", routes=mq_split_routes,
)
fake_clients_mq = Clients(supabase=fake_supabase_mq, voyage=fake_voyage, anthropic=fake_anthropic_mq)

result_multi_query = ask_question(
    MULTI_Q, match_count=3, use_multi_query=True, clients=fake_clients_mq,
    use_hybrid=False, use_hyde=False, expand_to_parents=False,
)
check("ask_question(use_multi_query=True) marks used_multi_query", result_multi_query["used_multi_query"] is True)
check("ask_question(use_multi_query=True) records the sub-questions searched",
      result_multi_query["subquestions"] == [
          "What is the RDA for protein?",
          "How much protein per kg is recommended?",
      ])
check("ask_question(use_multi_query=True) queried the dense RPC once per sub-question",
      sum(1 for name, _ in fake_supabase_mq.rpc_calls if name == "match_rag11_child_chunks") == 2)

result_multi_query_hyde_ignored = ask_question(
    MULTI_Q, match_count=3, use_multi_query=True, use_hyde=True, clients=fake_clients_mq,
    use_hybrid=False, expand_to_parents=False,
)
check("ask_question(use_multi_query=True, use_hyde=True) ignores use_hyde (hypothetical_document stays None)",
      result_multi_query_hyde_ignored["hypothetical_document"] is None
      and result_multi_query_hyde_ignored["used_multi_query"] is True)

fake_supabase_mq_hybrid = FakeSupabase(rpc_data={
    "match_rag11_child_chunks": dense_ranked,
    "match_rag11_child_chunks_keyword": keyword_ranked,
})
fake_clients_mq_hybrid = Clients(supabase=fake_supabase_mq_hybrid, voyage=fake_voyage, anthropic=fake_anthropic_mq)
result_multi_query_hybrid = ask_question(
    MULTI_Q, match_count=2, use_multi_query=True, use_hybrid=True, clients=fake_clients_mq_hybrid,
    use_hyde=False, expand_to_parents=False,
)
check("ask_question(use_multi_query=True, use_hybrid=True) marks both flags",
      result_multi_query_hybrid["used_multi_query"] is True and result_multi_query_hybrid["used_hybrid"] is True)
check("ask_question(use_multi_query=True, use_hybrid=True) queried both hybrid RPCs, once per sub-question",
      sum(1 for name, _ in fake_supabase_mq_hybrid.rpc_calls if name == "match_rag11_child_chunks") == 2
      and sum(1 for name, _ in fake_supabase_mq_hybrid.rpc_calls if name == "match_rag11_child_chunks_keyword") == 2)

# ---------------------------------------------------------------------------
# ask_question: expand_to_parents is optional, defaults to False, and runs
# last -- on whatever use_hybrid/use_hyde/use_rerank already selected.
# ---------------------------------------------------------------------------

check("ask_question() (no expand_to_parents arg) marks used_parent_expansion False",
      result_plain["used_parent_expansion"] is False)

# rows[0..2] (g1, g2, g3) all share rowParentGUID == "parent-1" -- plain
# retrieval should dedup them down to the one parent section.
result_expand = ask_question(
    "What is the RDA for protein?", match_count=3, expand_to_parents=True, clients=fake_clients_expand,
    use_hybrid=False, use_hyde=False, use_multi_query=False,
)
check("ask_question(expand_to_parents=True) marks used_parent_expansion",
      result_expand["used_parent_expansion"] is True)
check("ask_question(expand_to_parents=True) dedups chunks sharing one parent",
      result_expand["chunks_used"] == 1)
check("ask_question(expand_to_parents=True) computes 1-based source_pages from the parent's start_page/end_page",
      result_expand["source_pages"] == [41, 42, 43])

# ---------------------------------------------------------------------------
# env.optional_env_bool: parses the USE_* feature flags read by config.py
# ---------------------------------------------------------------------------

_BOOL_VAR = "RAG11_TEST_BOOL_FLAG_XYZ"
os.environ.pop(_BOOL_VAR, None)
check("optional_env_bool() falls back to default when the var is unset",
      optional_env_bool(_BOOL_VAR, True) is True)
check("optional_env_bool() falls back to default (False) when the var is unset",
      optional_env_bool(_BOOL_VAR, False) is False)

os.environ[_BOOL_VAR] = "False"
check("optional_env_bool() parses 'False'", optional_env_bool(_BOOL_VAR, True) is False)

os.environ[_BOOL_VAR] = "true"
check("optional_env_bool() parses 'true' case-insensitively", optional_env_bool(_BOOL_VAR, False) is True)

os.environ[_BOOL_VAR] = "not-a-bool"
try:
    optional_env_bool(_BOOL_VAR, True)
    check("optional_env_bool() raises on an unrecognized value", False)
except RuntimeError:
    check("optional_env_bool() raises on an unrecognized value", True)
os.environ.pop(_BOOL_VAR, None)

# ---------------------------------------------------------------------------
# config.py: ask_question()'s use_hybrid/use_hyde/use_multi_query/
# expand_to_parents keywords default to the matching config.py constant
# (each read once from .env, True if unset) -- so config.py is the single
# place that governs "simplest variant vs. full technique" repo-wide.
# ---------------------------------------------------------------------------

_ask_question_defaults = {
    name: param.default for name, param in inspect.signature(ask_question).parameters.items()
}
check("ask_question()'s use_hybrid default matches config.USE_HYBRID_SEARCH",
      _ask_question_defaults["use_hybrid"] == config_module.USE_HYBRID_SEARCH)
check("ask_question()'s use_hyde default matches config.USE_HYPOTHETICAL_DOCUMENT_EMBEDDING",
      _ask_question_defaults["use_hyde"] == config_module.USE_HYPOTHETICAL_DOCUMENT_EMBEDDING)
check("ask_question()'s use_multi_query default matches config.USE_MULTI_QUERY_QUESTION_SPLITTING",
      _ask_question_defaults["use_multi_query"] == config_module.USE_MULTI_QUERY_QUESTION_SPLITTING)
check("ask_question()'s expand_to_parents default matches config.USE_PARENT_CHUNK_EXPANSION",
      _ask_question_defaults["expand_to_parents"] == config_module.USE_PARENT_CHUNK_EXPANSION)

# ---------------------------------------------------------------------------
# devanagari.py: Devanagari -> IAST, and ask_question(filter_owner=, system_prompt=)
# ---------------------------------------------------------------------------

from reusable_code.devanagari import contains_devanagari, romanize_devanagari  # noqa: E402

check("romanize: Yoga-Sutra I.2", romanize_devanagari("योगश्चित्तवृत्तिनिरोधः") == "yogaścittavṛttinirodhaḥ")
check("romanize: anusvara + long vowel", romanize_devanagari("अहिंसा") == "ahiṃsā")
check("romanize: jñ and kṣ conjuncts", romanize_devanagari("ज्ञान क्षण") == "jñāna kṣaṇa")
check("romanize: Om, danda, digits", romanize_devanagari("ॐ । १२") == "oṃ . 12")
check("romanize: Latin/French text is left untouched",
      romanize_devanagari("Que dit योगः ? (I.2)") == "Que dit yogaḥ ? (I.2)")
check("contains_devanagari", contains_devanagari("what is योग") and not contains_devanagari("what is yoga"))

_plain_flags = dict(use_hybrid=False, use_hyde=False, use_multi_query=False, expand_to_parents=False)
ask_question("q?", match_count=3, filter_owner="owner-X", system_prompt="CUSTOM SYSTEM", clients=fake_clients, **_plain_flags)
check("ask_question(filter_owner=) reaches the dense RPC",
      fake_supabase.rpc_calls[-1][0] == "match_rag11_child_chunks" and fake_supabase.rpc_calls[-1][1].get("filter_owner") == "owner-X")
check("ask_question(system_prompt=) replaces the default system prompt",
      fake_anthropic.messages.calls[-1]["system"] == "CUSTOM SYSTEM")
ask_question("q?", match_count=3, clients=fake_clients, **_plain_flags)
check("ask_question() default: no filter_owner param sent",
      "filter_owner" not in fake_supabase.rpc_calls[-1][1])
check("ask_question() default system prompt is the nutrition one",
      fake_anthropic.messages.calls[-1]["system"] == SYSTEM_PROMPT_DEFAULT)

_n_before = len(fake_supabase_hybrid.rpc_calls)
ask_question("q?", match_count=3, use_hybrid=True, use_hyde=False, use_multi_query=False, expand_to_parents=False,
             filter_owner="owner-Y", clients=fake_clients_hybrid)
_new_calls = fake_supabase_hybrid.rpc_calls[_n_before:]
check("ask_question(use_hybrid=True, filter_owner=) filters BOTH the dense and keyword RPCs",
      len(_new_calls) == 2 and all(c[1].get("filter_owner") == "owner-Y" for c in _new_calls))

# ---------------------------------------------------------------------------
# language.py (question understanding + answer language) and display.py
# ---------------------------------------------------------------------------

from reusable_code.display import answer_html, format_pages, qa_card_html, summary_table_html  # noqa: E402
from reusable_code.language import (  # noqa: E402
    answer_language_directive,
    language_name,
    prepare_question,
)

check("language_name maps codes case-insensitively", language_name("en") == "English" and language_name("HI") == "Hindi")
check("answer_language_directive names the language and keeps the Short answer line English",
      "in English" in answer_language_directive("EN") and "Short answer: Yes" in answer_language_directive("EN"))

_understood = (
    'Sure! {"language": "fr", "translation": "Does dark chocolate count as a vegetable?", '
    '"search_query": "Is cocoa a vegetable? Classification of plant foods and vegetable servings"} Done.'
)
_anth = FakeAnthropic(answer_text=_understood)
_clients_lang = Clients(supabase=fake_supabase, voyage=fake_voyage, anthropic=_anth)
_prep = prepare_question("Le chocolat noir compte-t-il comme un légume ?", clients=_clients_lang)
check("prepare_question: JSON is extracted from a chatty reply", _prep.used_llm and _prep.language == "FR")
check("prepare_question: retrieval query is the model's clean search query",
      _prep.retrieval_query.startswith("Is cocoa a vegetable?"))
check("prepare_question: LLM sees original + translation when the language differs",
      _prep.llm_question.startswith("Le chocolat noir") and "[English: Does dark chocolate count as a vegetable?]" in _prep.llm_question)
check("prepare_question: system prompt names the speaking language and the corpus",
      "English" in _anth.messages.calls[-1]["system"] and "nutrition textbooks" in _anth.messages.calls[-1]["system"])

_en = FakeAnthropic(answer_text='{"language": "en", "translation": "Can I live on pizza?", "search_query": "Can a diet of only pizza meet nutrient needs?"}')
_prep_en = prepare_question("Can I live on pizza?", clients=Clients(supabase=fake_supabase, voyage=fake_voyage, anthropic=_en))
check("prepare_question: an English question is not annotated with a translation",
      _prep_en.llm_question == "Can I live on pizza?" and _prep_en.retrieval_query.startswith("Can a diet"))

_bad = FakeAnthropic(answer_text="I cannot help with that.")
_prep_bad = prepare_question("क्या योग है?", clients=Clients(supabase=fake_supabase, voyage=fake_voyage, anthropic=_bad))
check("prepare_question: garbage reply falls back to the question + IAST (never lost)",
      not _prep_bad.used_llm and "kyā yoga hai?" in _prep_bad.retrieval_query and "[IAST:" in _prep_bad.llm_question)
check("prepare_question(use_llm=False) makes no model call",
      prepare_question("x?", use_llm=False).retrieval_query == "x?")

_voy_before = len(fake_voyage.embed_calls)
_res_lang = ask_question("Le chocolat noir compte-t-il comme un légume ?", match_count=3,
                         retrieval_query="Is cocoa a vegetable?", answer_language="EN",
                         clients=fake_clients, **_plain_flags)
check("ask_question(retrieval_query=) embeds the search query, not the original question",
      fake_voyage.embed_calls[_voy_before][0] == ["Is cocoa a vegetable?"])
check("ask_question(retrieval_query=) still shows the model the original question",
      "Le chocolat noir" in fake_anthropic.messages.calls[-1]["messages"][0]["content"])
check("ask_question(answer_language=) appends the language directive to the system prompt",
      fake_anthropic.messages.calls[-1]["system"].endswith(answer_language_directive("EN")))
check("ask_question(answer_language=) repeats the language rule at the end of the user turn",
      fake_anthropic.messages.calls[-1]["messages"][0]["content"].endswith("not in the language of the question.)")
      and "Write your answer in English" in fake_anthropic.messages.calls[-1]["messages"][0]["content"])
check("ask_question() reports the retrieval query used", _res_lang["retrieval_query"] == "Is cocoa a vegetable?")

check("format_pages compresses ranges", format_pages([3, 4, 5, 13, 14, 20]) == "3-5, 13-14, 20" and format_pages([]) == "-")
_html = answer_html("**Bold** intro with *emph* & <tag>\n\n- one\n- two\n\nLast para")
check("answer_html: paragraphs, lists, inline styles, and escaping",
      "<p><b>Bold</b> intro with <i>emph</i> &amp; &lt;tag&gt;</p>" in _html and "<ul><li>one</li><li>two</li></ul>" in _html and "<p>Last para</p>" in _html)
_card = qa_card_html(1, "क्या योग है?", {"answer": "Short answer: No\n\nBody **x**", "short_answer": "No", "chunks_used": 3,
                     "candidates_considered": 9, "source_pages": [1, 2, 3], "subquestions": None, "grounding_words": ["yoga"]}, _prep_bad)
check("qa_card_html: Question/Answer labels, badge (no duplicate 'Short answer' line), IAST line, auto height",
      "Question 1:" in _card and "Answer:" in _card and 'ys-badge ys-no' in _card and _card.count("Short answer") == 1
      and "IAST: kyā yoga hai?" in _card and "overflow:visible" in __import__("reusable_code.display", fromlist=["CSS"]).CSS.replace(" ", ""))
check("summary_table_html escapes cells", "&lt;b&gt;" in summary_table_html([["<b>"]], ["h"]))

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(" -", f)
    sys.exit(1)
else:
    print("All checks passed.")
