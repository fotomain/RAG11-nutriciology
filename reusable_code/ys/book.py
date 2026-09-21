"""Locating the Yoga-Sutra book in Supabase and checking that it is fully loaded."""
from dataclasses import dataclass
from typing import Optional

from ..clients import Clients, get_clients

BOOK_FILENAME_LIKE = "%Yogasutra%"   # the source_key can change if files are added; the filename does not
SUTRA_TITLE_LIKE = "Yoga-S%tra%"     # parent sections are titled "Yoga-Sūtra I.2 (Samādhipāda) — ..."
EXPECTED_SUTRA_SECTIONS = 195


@dataclass(frozen=True)
class BookStatus:
    owner_guid: str
    source_key: str
    filename: str
    n_children: int
    n_sutra_sections: int

    @property
    def complete(self) -> bool:
        return self.n_sutra_sections >= EXPECTED_SUTRA_SECTIONS


def find_book(clients: Optional[Clients] = None) -> BookStatus:
    clients = clients or get_clients()
    rows = (clients.supabase.table("rag11_data_sources").select('"rowGUID",source_key,filename')
            .ilike("filename", BOOK_FILENAME_LIKE).execute().data)
    if not rows:
        raise RuntimeError(
            "The Yoga-Sutra book is not in the database. Run stage1_1_eda_extract_and_chunk.ipynb and "
            "stage1_2_eda_load_chunks.ipynb first."
        )
    guid = rows[0]["rowGUID"]
    n_children = (clients.supabase.table("rag11_chunks_child_table").select('"rowGUID"', count="exact")
                  .eq("rowOwnerGUID", guid).limit(1).execute().count)
    n_sutras = (clients.supabase.table("rag11_chunks_parent_table").select('"rowGUID"', count="exact")
                .eq("rowOwnerGUID", guid).like("title", SUTRA_TITLE_LIKE).limit(1).execute().count)
    return BookStatus(guid, rows[0]["source_key"], rows[0]["filename"], n_children or 0, n_sutras or 0)


def readiness_message(status: BookStatus) -> str:
    """One status line, plus what to do when the sutra text is not (fully) loaded."""
    line = (f"Yoga-Sutra book ready: {status.n_children} text chunks, "
            f"{status.n_sutra_sections} of {EXPECTED_SUTRA_SECTIONS} sutra sections loaded.")
    if status.complete:
        return line
    return (
        line + "\nWARNING: the sutra text is not fully loaded, so questions about individual sutras will be "
        "answered with 'the excerpts do not contain ...'. To load it:\n"
        "  1. in .env set MAX_NUMBER_OF_PAGES_TO_USE=NONE (and restart the notebook kernel)\n"
        "  2. re-run stage1_1_eda_extract_and_chunk.ipynb, then stage1_2_eda_load_chunks.ipynb "
        "(only new/changed chunks are embedded)\n"
        "  3. stage1_9_eda_verify_all_data.ipynb should print PASS"
    )
