#!/usr/bin/env python3
"""LRM reasoning CLI: ask a question against an uploaded LRM source from the terminal, the same
runnable-stage shape as eda1_extract/eda2_transform/eda3_load. Thin wrapper -- all the actual
logic is reusable_code.ask_question()/reusable_code.reasoning.ask_with_reasoning(); this script
only parses args, resolves --source-key/--language into the rowGUID they need, and prints the
result.

    python ask.py "What does the Yoga-Sutra say about ahimsa?" --source-key yogasutra_janvier_2020_pdf_d_2021 --language fr
    python ask.py "..." --reasoning              # force USE_REASONING on for this call
    python ask.py "..." --no-reasoning            # force it off
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # py/lrm/reasoning/
RAG = ROOT.parent.parent  # py/
sys.path.insert(0, str(RAG))
from reusable_code import USE_REASONING, ask_question, init_clients  # noqa: E402
from reusable_code.reasoning import ask_with_reasoning  # noqa: E402


def resolve_owner(sb, source_key: str | None, language: str | None) -> str | None:
    if not source_key:
        return None
    q = sb.table("lrm_source_table").select("rowGUID").eq("source_key", source_key)
    if language:
        q = q.eq("language", language)
    rows = q.limit(1).execute().data
    if not rows:
        raise SystemExit(f"no source {source_key!r}" + (f" [{language}]" if language else "") + " in lrm_source_table")
    return rows[0]["rowGUID"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question")
    ap.add_argument("--source-key", help="restrict to one book; omit to search every uploaded source")
    ap.add_argument("--language", help="narrows --source-key when the same book has multiple languages")
    ap.add_argument("--answer-language", help='ISO code, e.g. "EN" -- language the answer is written in')
    reasoning_group = ap.add_mutually_exclusive_group()
    reasoning_group.add_argument("--reasoning", action="store_true", help="force multi-step reasoning on")
    reasoning_group.add_argument("--no-reasoning", action="store_true", help="force multi-step reasoning off")
    args = ap.parse_args()

    clients = init_clients()
    filter_owner = resolve_owner(clients.supabase, args.source_key, args.language)
    use_reasoning = USE_REASONING
    if args.reasoning:
        use_reasoning = True
    elif args.no_reasoning:
        use_reasoning = False

    if use_reasoning:
        result = ask_with_reasoning(
            args.question, filter_owner=filter_owner, answer_language=args.answer_language, clients=clients,
        )
    else:
        result = ask_question(
            args.question, filter_owner=filter_owner, answer_language=args.answer_language, clients=clients,
        )

    print(f"Q: {result['question']}")
    if result["short_answer"]:
        print(f"Short answer: {result['short_answer']}")
    print()
    print(result["answer"])
    print()
    print(f"[{result['chunks_used']} chunk(s), source page(s) {result['source_pages']}, "
          f"source(s) {result['source_keys']}]")
    if result.get("reasoning_used"):
        print(f"[reasoning: {len(result['reasoning_steps'])} step(s), "
              f"verified={result['reasoning_verified']}]")
        for step in result["reasoning_steps"]:
            check = step.get("self_check")
            verdict = f", supported={check['supported']}" if check else ""
            print(f"  step {step['step']}: retrieval_query={step['retrieval_query']!r}{verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
