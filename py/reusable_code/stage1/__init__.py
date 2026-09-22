"""Stage 1 of RAG11 as importable, testable code -- the notebooks and run_stage1_all.command are thin wrappers.

    from reusable_code.stage1 import extract_chunk, load, verify      # step-by-step (what the notebooks do)
    from reusable_code.stage1.pipeline import run                      # everything

    python -m reusable_code.stage1 [--only 1.9 | --from 1.2] [--prune-orphans]
"""
