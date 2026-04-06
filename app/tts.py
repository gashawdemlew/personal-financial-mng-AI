import os
import uuid
import time
from typing import Dict
import wave

from langid import classify

from app.config import TTS_OUTPUT_DIR, TTS_FILE_TTL_SECONDS, GEMINI_API_KEY, GEMINI_TTS_MODEL, GEMINI_TTS_VOICE


def _detect_language(text: str) -> str:
    if not text or not text.strip():
        return "en"
    try:
        lang_code, _ = classify(text)
        return lang_code or "en"
    except Exception:
        return "en"


def _normalize_gtts_lang(lang_code: str) -> str:
    try:
        from gtts.lang import tts_langs
        available = tts_langs()
    except Exception:
        available = {"en": "English", "am": "Amharic"}
    if lang_code in available:
        return lang_code
    if lang_code and lang_code.startswith("am"):
        return "am" if "am" in available else "en"
    if lang_code and lang_code.startswith("en"):
        return "en"
    return "en"


def _wave_file(filename: str, pcm: bytes, channels: int = 1, rate: int = 24000, sample_width: int = 2):
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)


def cleanup_expired_tts_files() -> Dict:
    os.makedirs(TTS_OUTPUT_DIR, exist_ok=True)
    if TTS_FILE_TTL_SECONDS <= 0:
        return {"deleted_count": 0, "ttl_seconds": TTS_FILE_TTL_SECONDS}
    now = time.time()
    deleted = 0
    for name in os.listdir(TTS_OUTPUT_DIR):
        if not (name.endswith(".mp3") or name.endswith(".wav")):
            continue
        path = os.path.join(TTS_OUTPUT_DIR, name)
        try:
            if not os.path.isfile(path):
                continue
            age = now - os.path.getmtime(path)
            if age > TTS_FILE_TTL_SECONDS:
                os.remove(path)
                deleted += 1
        except Exception:
            continue
    return {"deleted_count": deleted, "ttl_seconds": TTS_FILE_TTL_SECONDS}


def _generate_tts_with_gemini(text: str, detected_lang: str) -> Dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    try:
        from google import genai
        from google.genai import types
    except Exception as e:
        raise RuntimeError("google-genai is not installed. Run: pip install google-genai") from e

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_TTS_MODEL,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=GEMINI_TTS_VOICE,
                    )
                )
            ),
        ),
    )
    data = response.candidates[0].content.parts[0].inline_data.data
    audio_id = str(uuid.uuid4())
    filename = f"{audio_id}.wav"
    path = os.path.join(TTS_OUTPUT_DIR, filename)
    _wave_file(path, data)
    return {
        "success": True,
        "audio_id": audio_id,
        "filename": filename,
        "language_detected": detected_lang,
        "language_used": detected_lang,
        "file_path": path,
        "provider": "gemini",
    }


def _generate_tts_with_gtts(text: str, detected_lang: str) -> Dict:
    try:
        from gtts import gTTS
    except Exception as e:
        raise RuntimeError("gTTS is not installed. Run: pip install gTTS") from e

    audio_id = str(uuid.uuid4())
    filename = f"{audio_id}.mp3"
    path = os.path.join(TTS_OUTPUT_DIR, filename)
    gtts_lang = _normalize_gtts_lang(detected_lang)
    tts = gTTS(text=text, lang=gtts_lang)
    tts.save(path)
    return {
        "success": True,
        "audio_id": audio_id,
        "filename": filename,
        "language_detected": detected_lang,
        "language_used": gtts_lang,
        "file_path": path,
        "provider": "gtts",
        "fallback_used": True,
    }


def generate_tts_audio(text: str) -> Dict:
    os.makedirs(TTS_OUTPUT_DIR, exist_ok=True)
    cleanup_expired_tts_files()
    detected = _detect_language(text)
    gemini_error = None
    try:
        return _generate_tts_with_gemini(text, detected_lang=detected)
    except Exception as e:
        gemini_error = str(e)

    try:
        result = _generate_tts_with_gtts(text, detected_lang=detected)
        result["gemini_error"] = gemini_error
        return result
    except Exception as e:
        raise RuntimeError(f"Gemini TTS failed: {gemini_error}; gTTS fallback failed: {e}")
