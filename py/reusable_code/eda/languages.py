"""Language metadata shared by the OCR/translate stages (py/lrm/eda1_extract): display name, the
name the OCR/translate prompts use, and per-language style notes for translate.py's prompt.

Used to live as eda1_extract/languages.json (per-stage data); moved here since it is the same
fixed metadata regardless of which book/stage is running -- shared, reusable, not stage-specific.
"""
from __future__ import annotations

LANGS: dict[str, dict] = {
    "fr": {"name": "Français", "short": "FR", "prompt_name": "French", "source": True},
    "en": {"name": "English", "short": "EN", "prompt_name": "American English (US)",
           "style": "- Use American English spelling and punctuation, with curly quotation marks “ ”."},
    "ru": {"name": "Русский", "short": "RU", "prompt_name": "Russian",
           "style": "- Write in a natural, literary scholarly Russian. Use «…» quotation marks and the em dash — "
                    "per Russian typography. Do not transliterate the Sanskrit or Latin kept in [[ ]]; leave it "
                    "in the source form."},
}
