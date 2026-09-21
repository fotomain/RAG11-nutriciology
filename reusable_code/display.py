"""Notebook display helpers shared by the stage2 Q&A notebooks (Question / Answer cards).

``show_qa()`` renders one ``ask_question()`` result as an HTML card: the Question, the Answer as real
paragraphs and lists (the model's Markdown converted by ``answer_html()``) with the ``Short answer`` line
turned into a Yes/No badge, and a muted footer with the retrieval details. The card has ``height: auto`` and
``overflow: visible`` so the whole answer always shows. Colours are semi-transparent so it reads in both
light and dark themes. ``show_summary()`` renders a matching summary table.

IPython is imported lazily, so importing this module never requires Jupyter.
"""
import html
import re
from typing import Iterable, Optional

from .devanagari import contains_devanagari, romanize_devanagari

CSS = """<style>
.ys-card{border:1px solid rgba(128,128,128,.35);border-radius:12px;padding:16px 20px;margin:18px 0;height:auto;
  max-height:none;overflow:visible;line-height:1.6;font-size:14.5px;max-width:980px}
.ys-label{font-size:11px;letter-spacing:.09em;text-transform:uppercase;font-weight:700;opacity:.6;margin:0 0 5px}
.ys-q{font-size:15.5px;font-weight:600;margin:0 0 4px;padding:9px 13px;border-left:4px solid #2a78d6;
  background:rgba(42,120,214,.10);border-radius:4px;white-space:pre-wrap;overflow-wrap:anywhere}
.ys-iast{font-size:12.5px;opacity:.7;margin:4px 0 0 17px;overflow-wrap:anywhere}
.ys-a{margin-top:14px;overflow-wrap:anywhere}
.ys-a p{margin:0 0 .85em}
.ys-a h4{margin:1em 0 .4em;font-size:1em}
.ys-a ul{margin:0 0 .85em 1.3em;padding:0}
.ys-a li{margin:.2em 0}
.ys-a code{background:rgba(128,128,128,.18);border-radius:4px;padding:0 4px}
.ys-badge{display:inline-block;padding:3px 12px;border-radius:999px;font-weight:700;font-size:12.5px;color:#fff;margin-bottom:10px}
.ys-yes{background:#0b7a4b}.ys-no{background:#b23b2e}
.ys-lang{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:700;margin-left:8px;
  border:1px solid rgba(128,128,128,.5);opacity:.8;letter-spacing:.04em}
.ys-meta{margin-top:12px;padding-top:9px;border-top:1px dashed rgba(128,128,128,.45);font-size:12px;opacity:.75;overflow-wrap:anywhere}
table.ys-tbl{border-collapse:collapse;font-size:13px;margin:10px 0}
table.ys-tbl th,table.ys-tbl td{border-bottom:1px solid rgba(128,128,128,.35);padding:5px 12px;text-align:left;vertical-align:top}
table.ys-tbl th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;opacity:.7}
</style>"""

UI = {
    "EN": {
        "question": "Question", "answer": "Answer", "short": "Short answer", "Yes": "Yes", "No": "No",
        "excerpts": "{n} excerpts (best of {c} candidates)", "pages": "pages", "subq": "sub-questions",
        "grounding": "established on", "understood": "Understood as", "search": "Search query",
        "col_no": "#", "col_lang": "question language", "col_short": "short answer", "col_subq": "sub-Qs",
        "col_excerpts": "excerpts", "col_question": "question",
    },
    "RU": {
        "question": "Вопрос", "answer": "Ответ", "short": "Краткий ответ", "Yes": "Да", "No": "Нет",
        "excerpts": "{n} фрагментов (лучшие из {c} кандидатов)", "pages": "страницы", "subq": "подвопросы",
        "grounding": "опирается на", "understood": "Понято как", "search": "Поисковый запрос",
        "col_no": "№", "col_lang": "язык вопроса", "col_short": "краткий ответ", "col_subq": "подвопросов",
        "col_excerpts": "фрагментов", "col_question": "вопрос",
    },
}


def ui(language: str = "EN") -> dict:
    """UI strings for ``language`` (an ISO code); languages without a translation use English."""
    return UI.get((language or "EN").upper(), UI["EN"])


_SHORT_ANSWER_LINE = re.compile(r"^\s*Short answer:\s*(Yes|No)\s*\n*", re.IGNORECASE)


def format_pages(pages: list) -> str:
    """[3, 4, 5, 13, 14] -> '3-5, 13-14' (a chunk's page range is its whole section's range)."""
    ranges, start = [], None
    for prev, page in zip([None] + list(pages), pages):
        if prev is None or page != prev + 1:
            if start is not None:
                ranges.append((start, prev))
            start = page
    if start is not None:
        ranges.append((start, pages[-1]))
    return ", ".join(f"{a}-{b}" if a != b else str(a) for a, b in ranges) or "-"


def _inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<i>\1</i>", text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


def answer_html(text: str) -> str:
    """Tiny Markdown -> HTML: headings, paragraphs, '-'/'*' bullet lists, **bold**, *italic*, `code`."""
    out, para, items = [], [], []

    def flush():
        if para:
            out.append("<p>" + "<br>".join(_inline(line) for line in para) + "</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        heading = re.match(r"^#{1,6}\s+(.*)", stripped)
        if heading:
            flush()
            out.append(f"<h4>{_inline(heading.group(1))}</h4>")
            continue
        bullet = re.match(r"^[-*•]\s+(.*)", stripped)
        if bullet:
            if para:
                flush()
            items.append(bullet.group(1))
        else:
            if items:
                flush()
            para.append(stripped)
    flush()
    return "".join(out)


def qa_card_html(number: int, question: str, result: dict, prepared=None, language: str = "EN") -> str:
    """HTML for one Question/Answer card. ``prepared`` is an optional ``language.PreparedQuestion`` whose
    detected language, translation and search query are shown under the question."""
    t = ui(language)
    answer = _SHORT_ANSWER_LINE.sub("", result["answer"], count=1).strip()
    badge = ""
    if result.get("short_answer"):
        cls = "ys-yes" if result["short_answer"] == "Yes" else "ys-no"
        badge = f'<div class="ys-badge {cls}">{t["short"]}: {t[result["short_answer"]]}</div>'

    lang_chip = f'<span class="ys-lang">{html.escape(prepared.language)}</span>' if prepared and prepared.language else ""
    under = []
    if contains_devanagari(question):
        under.append(f"IAST: {html.escape(romanize_devanagari(question))}")
    if prepared is not None and prepared.translation:
        under.append(f"{t['understood']}: {html.escape(prepared.translation)}")
    if prepared is not None and prepared.used_llm:
        under.append(f"{t['search']}: {html.escape(prepared.retrieval_query)}")
    under_html = "".join(f'<div class="ys-iast">{u}</div>' for u in under)

    meta = [
        t["excerpts"].format(n=result["chunks_used"], c=result["candidates_considered"]),
        f"{t['pages']} {format_pages(result['source_pages'])}",
    ]
    if result.get("subquestions") and len(result["subquestions"]) > 1:
        meta.append(f"{t['subq']}: " + " &#124; ".join(html.escape(q) for q in result["subquestions"]))
    if result.get("grounding_words"):
        meta.append(f"{t['grounding']}: " + html.escape(", ".join(result["grounding_words"])))

    return (
        '<div class="ys-card">'
        f'<div class="ys-label">{t["question"]} {number}:{lang_chip}</div><div class="ys-q">{html.escape(question)}</div>{under_html}'
        '<div class="ys-a"><div class="ys-label">' + t["answer"] + ':</div>' + badge + answer_html(answer) + "</div>"
        '<div class="ys-meta">' + "<br>".join(meta) + "</div></div>"
    )


def show_qa(number: int, question: str, result: dict, prepared=None, language: str = "EN") -> None:
    from IPython.display import HTML, display
    display(HTML(CSS + qa_card_html(number, question, result, prepared, language)))


def summary_table_html(rows: Iterable[Iterable], headers: Iterable[str]) -> str:
    head = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    return f'<table class="ys-tbl"><tr>{head}</tr>{body}</table>'


def show_summary(rows: Iterable[Iterable], headers: Iterable[str]) -> None:
    from IPython.display import HTML, display
    display(HTML(CSS + summary_table_html(rows, headers)))
