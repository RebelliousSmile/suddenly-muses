from __future__ import annotations

import spacy
from langdetect import detect, LangDetectException
from langdetect.detector_factory import DetectorFactory
from spacy.tokens import Doc

DetectorFactory.seed = 0

_nlp_fr: spacy.language.Language | None = None
_nlp_en: spacy.language.Language | None = None


def _get_nlp_fr() -> spacy.language.Language:
    global _nlp_fr
    if _nlp_fr is None:
        _nlp_fr = spacy.load(
            "fr_core_news_md",
            disable=["morphologizer", "parser", "attribute_ruler", "lemmatizer"],
        )
    return _nlp_fr


def _get_nlp_en() -> spacy.language.Language:
    global _nlp_en
    if _nlp_en is None:
        _nlp_en = spacy.load(
            "en_core_web_md",
            disable=["tagger", "parser", "senter", "attribute_ruler", "lemmatizer"],
        )
    return _nlp_en


def _detect_lang(text: str) -> str:
    try:
        lang = detect(text)
        return lang if lang in ("fr", "en") else "fr"
    except LangDetectException:
        return "fr"


def _nlp_for(text: str) -> spacy.language.Language:
    return _get_nlp_en() if _detect_lang(text) == "en" else _get_nlp_fr()


def _replace_persons(
    text: str,
    mapping: dict[str, str],
    counter: list[int],
    doc: Doc | None = None,
) -> str:
    if not text or not text.strip():
        return text
    if doc is None:
        nlp = _nlp_for(text)
        doc = nlp(text)
    persons = [ent for ent in doc.ents if ent.label_ == "PER"]
    if not persons:
        return text
    result, cursor = [], 0
    for ent in persons:
        result.append(text[cursor : ent.start_char])
        key = ent.text.lower()
        if key not in mapping:
            counter[0] += 1
            mapping[key] = f"[PER_{counter[0]}]"
        result.append(mapping[key])
        cursor = ent.end_char
    result.append(text[cursor:])
    return "".join(result)


def anonymize_session(messages: list[dict]) -> list[dict]:
    mapping: dict[str, str] = {}
    counter: list[int] = [0]

    # Detect language upfront; collect eligible (non-system, non-empty string) messages
    eligible: dict[int, tuple[str, str]] = {}
    for i, msg in enumerate(messages):
        if msg.get("role") == "system" or not isinstance(msg.get("content"), str):
            continue
        text = msg["content"]
        if text and text.strip():
            eligible[i] = (text, _detect_lang(text))

    # Batch NER via nlp.pipe() per language; store docs keyed by original index
    docs: dict[int, Doc] = {}
    fr_pairs = [(i, t) for i, (t, lang) in eligible.items() if lang == "fr"]
    en_pairs = [(i, t) for i, (t, lang) in eligible.items() if lang == "en"]

    if fr_pairs:
        for (idx, _), doc in zip(
            fr_pairs, _get_nlp_fr().pipe([t for _, t in fr_pairs], batch_size=50)
        ):
            docs[idx] = doc
    if en_pairs:
        for (idx, _), doc in zip(
            en_pairs, _get_nlp_en().pipe([t for _, t in en_pairs], batch_size=50)
        ):
            docs[idx] = doc

    # Assign [PER_N] in original message order so numbering matches sequential behaviour
    result = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system" or not isinstance(content, str):
            result.append(dict(msg))
            continue
        if i not in docs:
            result.append({**msg, "content": content})
            continue
        anonymized = _replace_persons(content, mapping, counter, doc=docs[i])
        result.append({**msg, "content": anonymized})

    return result
