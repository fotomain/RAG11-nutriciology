"""OCR_PROVIDER_NAME vision backends recognize.py dispatches to: google.py (Gemini, default) and
aws.py (Claude on AWS Bedrock). Each exposes DEFAULT_MODEL, make_client() and recognise()."""
