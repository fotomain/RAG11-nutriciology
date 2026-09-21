"""``YogaSutraQA``: everything a Yoga-Sutra notebook needs behind one small object.

    from reusable_code.ys import YogaSutraQA
    ys = YogaSutraQA(speaking_language="EN")   # connects, finds the book, checks it is loaded
    ys.ask_all(QUESTIONS)                      # understands, answers and displays every question

Per question it (1) understands the question (``prepare_question``: language, translation, a clean
search query in the book's language), (2) retrieves from THIS book only with hybrid search + multi-query
splitting + reranking, (3) answers strictly from the excerpts in ``speaking_language``, and (4) shows a
Question / Answer card (``display.show_qa``) in that language's UI strings.
"""
from dataclasses import dataclass
from typing import List, Optional

from ..clients import Clients, init_clients
from ..config import SPEAKING_LANGUAGE
from ..display import show_qa, show_summary, ui
from ..generation import ask_question
from ..language import PreparedQuestion, prepare_question
from .book import BookStatus, find_book, readiness_message
from .prompts import YS_CORPUS_HINT, YS_SYSTEM_PROMPT


@dataclass(frozen=True)
class YSAnswer:
    question: str
    prepared: PreparedQuestion
    result: dict          # the ask_question() result dict


class YogaSutraQA:
    def __init__(
        self,
        speaking_language: str = SPEAKING_LANGUAGE,
        *,
        match_count: int = 6,
        clients: Optional[Clients] = None,
        check_book: bool = True,
        verbose: bool = True,
    ):
        self.language = speaking_language.upper()
        self.match_count = match_count
        self.clients = clients or init_clients()
        self.book: BookStatus = find_book(self.clients)
        if verbose and check_book:
            print(readiness_message(self.book))

    def prepare(self, question: str) -> PreparedQuestion:
        return prepare_question(question, language=self.language, corpus_hint=YS_CORPUS_HINT, clients=self.clients)

    def ask(self, question: str, *, prepared: Optional[PreparedQuestion] = None, **overrides) -> YSAnswer:
        """Answer one question (no display). ``overrides`` are passed to ``ask_question``."""
        prepared = prepared or self.prepare(question)
        options = dict(
            match_count=self.match_count,
            use_hybrid=True,           # dense + keyword: exact sutra terms (IAST) are found by the keyword half
            use_multi_query=True,      # split compound questions into sub-questions
            use_hyde=False,
            use_rerank=True,           # cross-encoder re-scores the wide candidate pool
            expand_to_parents=False,   # a parent here is a whole sutra + commentary; keep the precise chunks
            filter_owner=self.book.owner_guid,
            system_prompt=YS_SYSTEM_PROMPT,
            answer_language=self.language,
            retrieval_query=prepared.retrieval_query,
            clients=self.clients,
        )
        options.update(overrides)
        return YSAnswer(question, prepared, ask_question(prepared.llm_question, **options))

    def ask_all(self, questions: List[str], *, show_table: bool = True) -> List[YSAnswer]:
        """Answer every question, displaying one Question / Answer card each, then a summary table."""
        answers = []
        for number, question in enumerate(questions, start=1):
            answer = self.ask(question)
            answers.append(answer)
            show_qa(number, question, answer.result, answer.prepared, self.language)
        if show_table:
            t = ui(self.language)
            show_summary(
                [
                    (i, a.prepared.language or "?", (a.result["short_answer"] and t[a.result["short_answer"]]) or "-",
                     len(a.result["subquestions"] or []), a.result["chunks_used"],
                     a.question[:80] + ("..." if len(a.question) > 80 else ""))
                    for i, a in enumerate(answers, start=1)
                ],
                [t["col_no"], t["col_lang"], t["col_short"], t["col_subq"], t["col_excerpts"], t["col_question"]],
            )
        return answers

    def compare_retrieval(self, question: str, match_count: int = 5) -> None:
        """Optional diagnostic: hybrid retrieval for the raw question vs. its search query."""
        from ..hybrid_search import hybrid_search
        prepared = self.prepare(question)
        for label, text in [("raw question", question), ("search query", prepared.retrieval_query)]:
            print(f"--- {label}: {text[:100]}")
            for r in hybrid_search(text, match_count=match_count, filter_owner=self.book.owner_guid, clients=self.clients):
                print(f"  dense#{r['dense_rank']!s:<4} keyword#{r['keyword_rank']!s:<5} "
                      f"{r['rowJSON']['text'].splitlines()[0][:95]}")
