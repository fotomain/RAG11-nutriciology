"""Run the whole stage 1 pipeline (or a slice of it): extract & chunk (1.1) -> load into Supabase (1.2) -> verify (1.9).

    python -m reusable_code.stage1                    # all three stages
    python -m reusable_code.stage1 --only 1.9         # just verify
    python -m reusable_code.stage1 --from 1.2         # load + verify (reuse the chunks already on disk)
    python -m reusable_code.stage1 --prune-orphans    # also delete Supabase rows that have no local file

Exit code: 0 = everything ran and stage 1.9 says PASS; 1 = ran, but verification found issues; 2 = a stage crashed.
run_stage1_all.command wraps this for double-click use.
"""
import argparse
import sys
import time
import traceback
from typing import List, Optional, Sequence

from .common import banner

STAGES = ("1.1", "1.2", "1.9")
STAGE_NAMES = {"1.1": "extract & chunk", "1.2": "embed & load", "1.9": "verify"}


def select_stages(only: Optional[str] = None, start: Optional[str] = None) -> List[str]:
    if only:
        return [only]
    return list(STAGES[STAGES.index(start):]) if start else list(STAGES)


def run(stages: Sequence[str] = STAGES, *, root=None, prune_orphans: bool = False) -> int:
    """Run ``stages`` in order; returns the process exit code (see module docstring)."""
    timings, verify_passed = [], None
    try:
        for stage in stages:
            t0 = time.monotonic()
            if stage == "1.1":
                from .extract_chunk import run_stage1_1
                run_stage1_1(root)
            elif stage == "1.2":
                from .load import run_stage1_2
                run_stage1_2(root, prune=prune_orphans)
            elif stage == "1.9":
                from .verify import run_stage1_9
                verify_passed = run_stage1_9(root).passed
            else:
                raise ValueError(f"unknown stage {stage!r}; choose from {', '.join(STAGES)}")
            timings.append((stage, time.monotonic() - t0))
    except KeyboardInterrupt:
        print("\nInterrupted. Every stage is resumable: just run it again.")
        return 2
    except Exception:  # noqa: BLE001 -- report which stage crashed, with the traceback
        traceback.print_exc()
        failed = stage
        print(f"\nSTAGE {failed} ({STAGE_NAMES.get(failed, '?')}) FAILED -- see the error above. "
              "Stages are idempotent, so fix the cause and run again.")
        return 2

    banner("Stage 1 summary")
    for stage, seconds in timings:
        print(f"  stage {stage}  {STAGE_NAMES[stage]:<16} {seconds:7.1f}s")
    if verify_passed is None:
        print("  (verification was not part of this run)")
        return 0
    print("  RESULT:", "PASS" if verify_passed else "FAIL (see stage 1.9 above)")
    return 0 if verify_passed else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m reusable_code.stage1", description=__doc__.split("\n\n")[0])
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--only", choices=STAGES, help="run just this stage")
    which.add_argument("--from", dest="start", choices=STAGES, help="run this stage and the ones after it")
    ap.add_argument("--prune-orphans", action="store_true",
                    help="stage 1.2: also DELETE Supabase parent/child rows that have no local file "
                         "(only rows of sources present locally are considered)")
    ap.add_argument("--root", default=None, help="project root (default: current directory)")
    args = ap.parse_args(argv)
    return run(select_stages(args.only, args.start), root=args.root, prune_orphans=args.prune_orphans)


if __name__ == "__main__":
    sys.exit(main())
