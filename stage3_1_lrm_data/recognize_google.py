"""OCR_PROVIDER_NAME=ocr_with_google: page recognition via Gemini.

Called by recognize.py. Exposes DEFAULT_MODEL, make_client() and recognise().
"""
from __future__ import annotations

import json
import os
import sys

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

DEFAULT_MODEL = os.getenv("GOOGLE_AI_MODEL_NAME") or "gemini-3.6-flash"


def api_key() -> str:
    key = os.getenv("GOOGLE_AI_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        sys.exit("Set GOOGLE_AI_API_KEY in .env")
    return key


def make_client(model: str | None = None):
    return genai.Client(api_key=api_key())


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=5, max=60), reraise=True)
def recognise(client, model: str, png: bytes, prompt: str, schema: dict) -> dict:
    resp = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=png, mime_type="image/png"), prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=schema,
            temperature=0.0, max_output_tokens=65000),
    )
    data = json.loads(resp.text)  # truncated/invalid JSON raises -> retried
    if not data.get("blocks"):
        raise ValueError("no blocks recognised")
    return data
