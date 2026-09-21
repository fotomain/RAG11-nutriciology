"""Offline tests for reusable_code/ys (Yoga-Sutra Q&A) with fake Supabase/Voyage/Anthropic clients.
Run: .venv/bin/python test_ys.py"""
import sys
from types import SimpleNamespace

sys.path.insert(0, ".")
import IPython.display as ipd  # noqa: E402

from reusable_code.clients import Clients  # noqa: E402
from reusable_code.ys import YogaSutraQA, find_book, readiness_message  # noqa: E402
from reusable_code.ys.book import BookStatus  # noqa: E402

FAILURES = []


def check(label, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILURES.append(label)


GUID = "book-guid-1"


class Result:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class Query:
    def __init__(self, sb, table):
        self.sb, self.table, self.filters = sb, table, {}

    def select(self, *a, **k): return self
    def ilike(self, col, pat): self.filters["ilike"] = (col, pat); return self
    def like(self, col, pat): self.filters["like"] = (col, pat); return self
    def eq(self, col, val): self.filters["eq"] = (col, val); return self
    def limit(self, n): return self

    def execute(self):
        if self.table == "rag11_data_sources":
            return Result(self.sb.sources)
        if self.table == "rag11_chunks_child_table":
            return Result([], count=self.sb.n_children)
        return Result([], count=self.sb.n_sutras)


class FakeSupabase:
    def __init__(self, sources=None, n_children=314, n_sutras=195):
        self.sources = [{"rowGUID": GUID, "source_key": "source18", "filename": "Yogasutra.pdf"}] if sources is None else sources
        self.n_children, self.n_sutras = n_children, n_sutras
        self.rpc_calls = []

    def table(self, name): return Query(self, name)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        rows = [{
            "rowGUID": f"c{i}", "rowParentGUID": "p1", "rowOwnerGUID": GUID, "orderInList": i,
            "cosine_distance": 0.1 * i, "text_rank": 1.0 - 0.1 * i,
            "rowJSON": {"source_key": "source18", "text": f"[Source: Yogasutra.pdf | Section: Yoga-Sutra II.35 | Pages 5{i}-5{i}]\n\nahimsa text {i}"},
        } for i in range(1, 5)]
        return SimpleNamespace(execute=lambda: Result(rows[: params.get("match_count", 4)]))


class FakeVoyage:
    def __init__(self): self.embeds = []
    def embed(self, texts, model, input_type):
        self.embeds.append((texts, input_type)); return SimpleNamespace(embeddings=[[0.1, 0.2]])
    def rerank(self, query, documents, model, top_k, truncation=True):
        return SimpleNamespace(results=[SimpleNamespace(index=i, relevance_score=0.9 - 0.1 * i) for i in range(min(top_k, len(documents)))])


class FakeAnthropic:
    def __init__(self, yes_no=False):
        self.calls, self.yes_no = [], yes_no
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        system = kw.get("system", "")
        if "You prepare user questions" in system:
            text = ('{"language": "ru", "translation": "Is Ishvara a creator?", '
                    '"search_query": "Ishvara est-il le createur du monde selon le Yoga-sutra ?"}')
        elif "split" in system.lower() and "SUBQ" in system:
            text = "SUBQ: Ishvara est-il le createur du monde selon le Yoga-sutra ?"
        else:
            text = ("Short answer: No\n\n# Heading\n\nBody **bold**" if self.yes_no else "Plain answer")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def make(sb=None, anth=None, lang="RU"):
    sb, voy, anth = sb or FakeSupabase(), FakeVoyage(), anth or FakeAnthropic(yes_no=True)
    clients = Clients(supabase=sb, voyage=voy, anthropic=anth)
    return YogaSutraQA(speaking_language=lang, clients=clients, verbose=False), sb, voy, anth


# ---- book lookup / readiness
status = find_book(Clients(supabase=FakeSupabase(), voyage=None, anthropic=None))
check("find_book returns the book's guid and counts", status.owner_guid == GUID and status.n_sutra_sections == 195 and status.complete)
check("readiness_message: complete book has no warning", "WARNING" not in readiness_message(status))
partial = BookStatus(GUID, "source18", "x.pdf", 314, 0)
msg = readiness_message(partial)
check("readiness_message: incomplete book explains the .env fix", "WARNING" in msg and "MAX_NUMBER_OF_PAGES_TO_USE=NONE" in msg and "0 of 195" in msg)
try:
    find_book(Clients(supabase=FakeSupabase(sources=[]), voyage=None, anthropic=None))
    check("find_book raises a clear error when the book is absent", False)
except RuntimeError as e:
    check("find_book raises a clear error when the book is absent", "not in the database" in str(e))

# ---- ask(): one question end to end
ys, sb, voy, anth = make()
ans = ys.ask("Является ли Ишвара в Йога-сутре творцом мира?")
check("ask: understanding step ran and detected the language", ans.prepared.used_llm and ans.prepared.language == "RU")
check("ask: every retrieval RPC is restricted to the book (filter_owner)",
      sb.rpc_calls and all(p.get("filter_owner") == GUID for _n, p in sb.rpc_calls))
check("ask: retrieval embeds the clean search query, not the Russian question",
      all("Ishvara est-il" in t[0][0] for t in voy.embeds if t[1] == "query"))
final = anth.calls[-1]
check("ask: final call uses the Yoga system prompt and forces Russian",
      "Yoga-Sutra of" in final["system"] and "Russian" in final["system"] and "Write your answer in Russian" in final["messages"][0]["content"])
check("ask: yes/no answer parsed, parent expansion off, book pages used",
      ans.result["short_answer"] == "No" and ans.result["used_parent_expansion"] is False and ans.result["source_pages"])

# ---- ask_all(): cards + table displayed in the speaking language
shown = []
ipd.display = lambda obj, *a, **k: shown.append(obj.data)
answers = ys.ask_all(["Является ли Ишвара творцом?", "Что такое ниродха?"])
html_all = "\n".join(shown)
check("ask_all: one card per question plus one summary table", len(answers) == 2 and html_all.count('class="ys-card"') == 2 and html_all.count('class="ys-tbl"') == 1)
check("ask_all: Russian UI strings and localised badge", "Вопрос 1:" in html_all and "Ответ:" in html_all and "Краткий ответ: Нет" in html_all and "язык вопроса" in html_all)
check("ask_all: heading and bold from the model's Markdown are rendered", "<h4>Heading</h4>" in html_all and "<b>bold</b>" in html_all)

ys_en, *_ = make(lang="EN")
shown.clear()
ys_en.ask_all(["Is Ishvara a creator?"], show_table=False)
check("EN notebook: English labels, no table when show_table=False", "Question 1:" in shown[0] and len(shown) == 1)

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(" -", f)
    sys.exit(1)
print("All checks passed.")
