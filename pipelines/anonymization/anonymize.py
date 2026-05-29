from __future__ import annotations

import spacy
from langdetect import detect, LangDetectException
from langdetect.detector_factory import DetectorFactory

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


def anonymize_session(messages: list[dict]) -> list[dict]:
    mapping: dict[str, str] = {}
    counter = 0
    result = list(messages)

    processable = [
        (i, msg["content"])
        for i, msg in enumerate(messages)
        if msg.get("role") != "system" and isinstance(msg.get("content"), str)
    ]
    if not processable:
        return result

    indices_texts = processable
    langs = [_detect_lang(t) for _, t in indices_texts]

    fr_pairs = [(idx, t) for (idx, t), lang in zip(indices_texts, langs) if lang == "fr"]
    en_pairs = [(idx, t) for (idx, t), lang in zip(indices_texts, langs) if lang == "en"]

    anonymized: dict[int, str] = {}

    def _apply_ner_batch(nlp: spacy.language.Language, pairs: list[tuple[int, str]]) -> None:
        nonlocal counter
        for (msg_idx, text), doc in zip(pairs, nlp.pipe([t for _, t in pairs], batch_size=50)):
            persons = [ent for ent in doc.ents if ent.label_ == "PER"]
            if not persons:
                anonymized[msg_idx] = text
                continue
            parts, cursor = [], 0
            for ent in persons:
                parts.append(text[cursor : ent.start_char])
                key = ent.text.lower()
                if key not in mapping:
                    counter += 1
                    mapping[key] = f"[PER_{counter}]"
                parts.append(mapping[key])
                cursor = ent.end_char
            parts.append(text[cursor:])
            anonymized[msg_idx] = "".join(parts)

    if fr_pairs:
        _apply_ner_batch(_get_nlp_fr(), fr_pairs)
    if en_pairs:
        _apply_ner_batch(_get_nlp_en(), en_pairs)

    for i, msg in enumerate(messages):
        if i in anonymized:
            result[i] = {**msg, "content": anonymized[i]}
        else:
            result[i] = dict(msg)

    return result
