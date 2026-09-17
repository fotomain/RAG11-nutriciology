"""Shared "save this notebook (and any code changes) to GitHub" helper.

Wraps the repo's existing ``save_to_github.command`` (bulletproof
commit/push with stale-lock recovery and conflict resolution) so every
notebook calls the same one-line function instead of re-pasting the
subprocess boilerplate.
"""
import os
import subprocess
import sys


def save_to_github(commit_msg: str = "Update notebook") -> bool:
    """Run ``save_to_github.command`` from the repo root with
    ``commit_msg``, printing its output, and return whether it succeeded."""
    env = dict(os.environ, NON_INTERACTIVE="1")
    res = subprocess.run(
        ["/bin/zsh", "save_to_github.command", commit_msg],
        capture_output=True,
        text=True,
        env=env,
    )
    print(res.stdout)
    if res.stderr:
        print(res.stderr, file=sys.stderr)
    return res.returncode == 0
