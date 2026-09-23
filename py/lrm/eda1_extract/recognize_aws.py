"""OCR_PROVIDER_NAME=ocr_with_aws: page recognition via Claude on AWS Bedrock.

Called by recognize.py. Exposes DEFAULT_MODEL, make_client() and recognise().
Needs AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION + BEDROCK_MODEL_ID in .env,
and Bedrock model access enabled for that model in the AWS console.
"""
from __future__ import annotations

import os
import sys

from tenacity import retry, stop_after_attempt, wait_exponential

DEFAULT_MODEL = os.getenv("BEDROCK_MODEL_ID")
TOOL_NAME = "return_page"


def make_client(model: str | None = None):
    if not model:
        sys.exit("Set BEDROCK_MODEL_ID in .env (or pass --model) to the exact model id/inference-profile ARN "
                  "from the Bedrock console's model catalog (Anthropic > Claude).")
    if not (os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")):
        sys.exit("Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env")
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if not region:
        sys.exit("Set AWS_REGION in .env (e.g. us-east-1) — must be a region where the model is enabled")
    import boto3
    return boto3.client("bedrock-runtime", region_name=region)


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=5, max=60), reraise=True)
def recognise(client, model: str, png: bytes, prompt: str, schema: dict) -> dict:
    """Same schema/prompt as Gemini, via Claude's Converse API (tool-use forces the JSON shape)."""
    resp = client.converse(
        modelId=model,
        messages=[{
            "role": "user",
            "content": [
                {"image": {"format": "png", "source": {"bytes": png}}},
                {"text": prompt},
            ],
        }],
        toolConfig={
            "tools": [{"toolSpec": {
                "name": TOOL_NAME,
                "description": "Return the recognised page as structured JSON matching the schema.",
                "inputSchema": {"json": schema},
            }}],
            "toolChoice": {"tool": {"name": TOOL_NAME}},
        },
        inferenceConfig={"temperature": 0.0, "maxTokens": int(os.getenv("BEDROCK_MAX_TOKENS") or 8192)},
    )
    for block in resp["output"]["message"]["content"]:
        tool_use = block.get("toolUse")
        if tool_use and tool_use["name"] == TOOL_NAME:
            data = tool_use["input"]
            if not data.get("blocks"):
                raise ValueError("no blocks recognised")
            return data
    raise ValueError("Bedrock response had no toolUse block")
