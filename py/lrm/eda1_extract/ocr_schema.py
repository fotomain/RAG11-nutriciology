"""JSON schema + prompt shared by every OCR provider (recognize_google.py, recognize_aws.py).

Kept separate from recognize.py so both provider modules can import it without
importing each other or the orchestrator (which imports them).
"""
from __future__ import annotations

BLOCK_TYPES = ["running_header", "running_footer", "page_number", "heading", "sutra",
               "paragraph", "footnote", "list_item", "quote", "table", "caption", "figure", "other"]

_INT_ARRAY = {"type": "array", "items": {"type": "integer"}}
SCHEMA = {
    "type": "object",
    "properties": {
        "printed_page_number": {"type": "string", "description": "page number printed on the page, '' if none"},
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "block_id": {"type": "string", "description": "local id b1, b2, ... in reading order"},
                    "type": {"type": "string", "enum": BLOCK_TYPES},
                    "box": {**_INT_ARRAY, "description": "[ymin,xmin,ymax,xmax] of the block, 0-1000 of the full page image"},
                    "parent_block_id": {"type": "string", "description": "footnote -> block b# that contains its marker; commentary -> its sutra block; '' otherwise"},
                    "footnote_marker": {"type": "string", "description": "for a footnote block: its number/marker"},
                    "sutra_ref": {"type": "string", "description": "e.g. '1.2' for a sutra block, else ''"},
                    "section_path": {"type": "array", "items": {"type": "string"}, "description": "chapter/section titles in force, outermost first"},
                    "continues_from_previous_page": {"type": "boolean"},
                    "continues_on_next_page": {"type": "boolean"},
                    "words": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "t": {"type": "string", "description": "the word exactly as printed, punctuation attached"},
                                "box": {**_INT_ARRAY, "description": "[ymin,xmin,ymax,xmax] tight box, 0-1000 of the full page image"},
                                "lang": {"type": "string", "enum": ["src", "sa", "la", "other"]},
                                "style": {"type": "string", "enum": ["normal", "italic", "bold", "sup", "sub"]},
                            },
                            "required": ["t", "box", "lang", "style"],
                        },
                    },
                },
                "required": ["block_id", "type", "box", "words"],
            },
        },
    },
    "required": ["blocks"],
}

PROMPT = """This image is one page of a scholarly book written in {language}, possibly with Sanskrit (Devanagari and IAST
transliteration), Latin, footnotes, superscript markers and mixed typography.
Perform exact layout-aware OCR and return JSON per the schema.

- Transcribe the TRUE characters from the image. Sanskrit in IAST must carry real diacritics (ā ī ū ṛ ṅ ñ ṭ ḍ ṇ ś ṣ ṃ ḥ);
  Devanagari must be real Devanagari. Never invent, translate, normalise or correct the text.
- Split the page into blocks in natural reading order: running header/footer and page number, headings, sutra text,
  paragraphs, footnotes (the small-type notes at the bottom), lists, quotes, tables, captions.
- Every block lists ALL its words in reading order. A word is a whitespace-delimited token with its punctuation attached.
  Footnote/superscript markers are their own word with style "sup". Words split by an end-of-line hyphen are kept as printed
  (two tokens, each with its own box).
- Boxes are [ymin, xmin, ymax, xmax] integers, 0-1000, relative to the WHOLE image. Word boxes must be tight and accurate,
  since they will be overlaid on the image; block boxes enclose their words.
- lang: "src" for the book's main language ({language}), "sa" for Sanskrit (any script), "la" for Latin, "other" for the rest
  (numbers, references, other languages).
- Link footnote blocks to the block whose text carries the matching marker via parent_block_id; link commentary to its sutra.
- Set continues_from_previous_page / continues_on_next_page for blocks cut by the page boundary.
"""
