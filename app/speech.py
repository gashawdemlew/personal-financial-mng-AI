from typing import Dict

from app.config import GEMINI_API_KEY, GEMINI_STT_MODEL


def _gemini_client():
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    try:
        from google import genai
    except Exception as e:
        raise RuntimeError("google-genai is not installed. Run: pip install google-genai") from e
    return genai.Client(api_key=GEMINI_API_KEY)


def is_rate_limited_error(message: str) -> bool:
    m = (message or "").lower()
    return ("429" in m) or ("rate" in m and "limit" in m) or ("quota" in m) or ("resource_exhausted" in m)


def transcribe_audio_with_gemini(audio_bytes: bytes, mime_type: str = "audio/webm") -> Dict:
    if not audio_bytes:
        raise ValueError("audio content is empty")

    client = _gemini_client()
    try:
        from google.genai import types
    except Exception as e:
        raise RuntimeError("google-genai types import failed") from e

    prompt = (
        "Please transcribe this English or Amharic (Ethiopia language) audio into text accurately. "
        "Return only transcription text."
    )
    part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)

    response = client.models.generate_content(
        model=GEMINI_STT_MODEL,
        contents=[prompt, part],
    )
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise RuntimeError("empty transcription from model")
    return {"success": True, "text": text}
