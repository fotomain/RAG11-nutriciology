"""Locating the Yoga-Sutra book in Supabase and checking that it is fully loaded."""
from dataclasses import dataclass
from typing import Optional

from ..clients import Clients, get_clients

# source_key is a slug of the PDF filename (see py/lrm/eda1_extract/download.py's detect()/slug()), not the
# filename itself -- lrm_source_table has no filename column, only source_key/language/title.
BOOK_SOURCE_KEY_LIKE = "%yogasutra%"


@dataclass(frozen=True)
class BookStatus:
    owner_guid: str
    source_key: str
    title: str
    n_chunks: int
    n_pages_loaded: int
    expected_pages: Optional[int]

    @property
    def complete(self) -> bool:
        """Every page has been recognised/translated for this source+language."""
        return self.expected_pages is not None and self.n_pages_loaded >= self.expected_pages

    @property
    def ready(self) -> bool:
        """Complete AND chunked+embedded -- what actually matters for asking questions."""
        return self.complete and self.n_chunks > 0


def find_book(clients: Optional[Clients] = None) -> BookStatus:
    clients = clients or get_clients()
    rows = (clients.supabase.table("lrm_source_table").select('"rowGUID",source_key,title,"rowJSON"')
            .ilike("source_key", BOOK_SOURCE_KEY_LIKE).execute().data)
    if not rows:
        raise RuntimeError(
            "The Yoga-Sutra book is not in the database. First time only: paste sql/create_lrm_tables.sql "
            "into the Supabase SQL Editor and run it. Then run the LRM pipeline: "
            "py/run/run1_lrm_eda.command, then run2_lrm_upload.command."
        )
    row = rows[0]
    guid = row["rowGUID"]
    n_chunks = (clients.supabase.table("lrm_child_chunk_table").select('"rowGUID"', count="exact")
                .eq("rowOwnerGUID", guid).limit(1).execute().count)
    n_pages = (clients.supabase.table("lrm_page_table").select('"rowGUID"', count="exact")
               .eq("rowOwnerGUID", guid).limit(1).execute().count)
    expected = row["rowJSON"].get("page_count")
    return BookStatus(guid, row["source_key"], row["title"], n_chunks or 0, n_pages or 0, expected)


def readiness_message(status: BookStatus) -> str:
    """One status line, plus what to do when the book is not (fully) loaded/chunked."""
    expected = status.expected_pages if status.expected_pages is not None else "an unknown number of"
    line = (f"Yoga-Sutra book ready: {status.n_pages_loaded} of {expected} page(s) recognised, "
            f"{status.n_chunks} chunk(s) embedded.")
    if status.ready:
        return line
    return (
        line + "\nWARNING: the book is not fully loaded/chunked yet, so some questions may be answered with "
        "'the excerpts do not contain ...'. To load it:\n"
        "  1. in .env set MAX_NUMBER_OF_PAGES_TO_USE=NONE (and restart the notebook kernel)\n"
        "  2. re-run py/run/run1_lrm_eda.command\n"
        "  3. run2_lrm_upload.command\n"
    )
