#!/usr/bin/env python3
"""LRM stage 3.1 step 0: download every PDF of LRM_SOURCES_FOLDER (Google Drive, from .env) into
input/<lang>/. Thin wrapper -- all the actual logic (language detection, gdown call) is
reusable_code.eda.download.download_sources()."""
import sys
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent  # py/lrm/eda1_extract/
ROOT = HERE.parent.parent  # py/
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from reusable_code.eda.download import download_sources  # noqa: E402


def main() -> int:
    for dest in download_sources(HERE / "input"):
        print("downloaded", dest.relative_to(HERE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
