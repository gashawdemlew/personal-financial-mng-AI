from typing import Dict, List, Tuple


def _split_by_word_limit(text: str, max_chars: int = 2000) -> List[str]:
    words = (text or "").split()
    if not words:
        return []
    chunks: List[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current += (word + " ")
        else:
            chunks.append(current.strip())
            current = word + " "
    if current.strip():
        chunks.append(current.strip())
    return chunks


def detect_language(text: str) -> str:
    sample = (text or "").strip()
    if not sample:
        return "unknown"
    sample = sample[:5000]
    try:
        from langid import classify
        lang_code, _ = classify(sample)
        return lang_code or "unknown"
    except Exception:
        return "unknown"


def _translate_chunk_deep_translator(chunk: str) -> str:
    from deep_translator import GoogleTranslator
    return GoogleTranslator(source="am", target="en").translate(text=chunk)


def _translate_chunk_googletrans(chunk: str) -> str:
    from googletrans import Translator
    translator = Translator()
    translated = translator.translate(chunk, src="am", dest="en")
    return translated.text


def translate_amharic_to_english(text: str) -> Tuple[str, Dict]:
    chunks = _split_by_word_limit(text, max_chars=2000)
    if not chunks:
        return text, {"translated": False, "method": "none", "failed_chunks": 0}

    translated_parts: List[str] = []
    failed_chunks = 0
    method_used = "deep_translator"

    for chunk in chunks:
        try:
            translated_parts.append(_translate_chunk_deep_translator(chunk))
            continue
        except Exception:
            method_used = "googletrans_fallback"
        try:
            translated_parts.append(_translate_chunk_googletrans(chunk))
        except Exception:
            failed_chunks += 1
            translated_parts.append(chunk)

    translated_text = " ".join(translated_parts).strip()
    return translated_text, {
        "translated": True,
        "method": method_used,
        "failed_chunks": failed_chunks,
        "chunk_count": len(chunks),
    }


def _translate_chunk_deep_translator_en_to_am(chunk: str) -> str:
    from deep_translator import GoogleTranslator
    return GoogleTranslator(source="en", target="am").translate(text=chunk)


def _translate_chunk_googletrans_en_to_am(chunk: str) -> str:
    from googletrans import Translator
    translator = Translator()
    translated = translator.translate(chunk, src="en", dest="am")
    return translated.text


def translate_english_to_amharic(text: str) -> Tuple[str, Dict]:
    chunks = _split_by_word_limit(text, max_chars=2000)
    if not chunks:
        return text, {"translated": False, "method": "none", "failed_chunks": 0}

    translated_parts: List[str] = []
    failed_chunks = 0
    method_used = "deep_translator"

    for chunk in chunks:
        try:
            translated_parts.append(_translate_chunk_deep_translator_en_to_am(chunk))
            continue
        except Exception:
            method_used = "googletrans_fallback"
        try:
            translated_parts.append(_translate_chunk_googletrans_en_to_am(chunk))
        except Exception:
            failed_chunks += 1
            translated_parts.append(chunk)

    translated_text = " ".join(translated_parts).strip()
    return translated_text, {
        "translated": True,
        "method": method_used,
        "failed_chunks": failed_chunks,
        "chunk_count": len(chunks),
    }


def normalize_text_to_english(text: str) -> Tuple[str, Dict]:
    lang = detect_language(text)
    if lang == "am":
        translated, meta = translate_amharic_to_english(text)
        return translated, {"source_language": lang, **meta}
    return text, {"source_language": lang, "translated": False, "method": "none", "failed_chunks": 0}


def back_translate_answer_if_needed(answer_text: str, source_language: str) -> Tuple[str, Dict]:
    if (source_language or "").lower() != "am":
        return answer_text, {"translated": False, "method": "none"}
    translated, meta = translate_english_to_amharic(answer_text)
    return translated, meta
