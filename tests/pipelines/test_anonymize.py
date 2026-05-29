from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("spacy", reason="spacy non installé (extra `pipelines`)")

from pipelines.anonymization.anonymize import _detect_lang, _replace_persons, anonymize_session  # noqa: E402

MODULE = "pipelines.anonymization.anonymize"


def _make_ent(text: str, label: str, start_char: int, end_char: int) -> MagicMock:
    ent = MagicMock()
    ent.text = text
    ent.label_ = label
    ent.start_char = start_char
    ent.end_char = end_char
    return ent


def _make_doc(ents: list) -> MagicMock:
    doc = MagicMock()
    doc.ents = ents
    return doc


def _make_nlp(entities_by_text: dict[str, list[tuple]]):
    """Mock nlp supporting both __call__ and .pipe()."""

    def _call(text: str) -> MagicMock:
        raw_ents = entities_by_text.get(text, [])
        return _make_doc([_make_ent(t, lbl, s, e) for t, lbl, s, e in raw_ents])

    mock = MagicMock()
    mock.side_effect = _call
    mock.pipe = lambda texts, batch_size=50: (_call(t) for t in texts)  # noqa: E731
    return mock


class TestReplaceFR:
    def test_single_person(self):
        text = "Marie demande de l'aide."
        nlp = _make_nlp({text: [("Marie", "PER", 0, 5)]})
        with patch(f"{MODULE}._nlp_for", return_value=nlp):
            mapping, counter = {}, [0]
            result = _replace_persons(text, mapping, counter)
        assert result == "[PER_1] demande de l'aide."
        assert mapping == {"marie": "[PER_1]"}

    def test_two_persons(self):
        text = "Marie demande à Jean de l'aider."
        nlp = _make_nlp({text: [("Marie", "PER", 0, 5), ("Jean", "PER", 16, 20)]})
        with patch(f"{MODULE}._nlp_for", return_value=nlp):
            mapping, counter = {}, [0]
            result = _replace_persons(text, mapping, counter)
        assert result == "[PER_1] demande à [PER_2] de l'aider."

    def test_same_person_twice(self):
        text = "Jean parle. Jean écoute."
        nlp = _make_nlp({text: [("Jean", "PER", 0, 4), ("Jean", "PER", 12, 16)]})
        with patch(f"{MODULE}._nlp_for", return_value=nlp):
            mapping, counter = {}, [0]
            result = _replace_persons(text, mapping, counter)
        assert result == "[PER_1] parle. [PER_1] écoute."
        assert counter[0] == 1


class TestReplaceEN:
    def test_single_person(self):
        text = "Alice asks for help."
        nlp = _make_nlp({text: [("Alice", "PER", 0, 5)]})
        with patch(f"{MODULE}._nlp_for", return_value=nlp):
            mapping, counter = {}, [0]
            result = _replace_persons(text, mapping, counter)
        assert result == "[PER_1] asks for help."

    def test_two_persons(self):
        text = "Alice meets Bob at the crossroads."
        nlp = _make_nlp({text: [("Alice", "PER", 0, 5), ("Bob", "PER", 12, 15)]})
        with patch(f"{MODULE}._nlp_for", return_value=nlp):
            mapping, counter = {}, [0]
            result = _replace_persons(text, mapping, counter)
        assert result == "[PER_1] meets [PER_2] at the crossroads."


class TestSessionCoherence:
    def test_cross_message_coherence(self):
        msg_user = "Marie demande à Jean de l'aider."
        msg_asst = "Jean acquiesce."
        nlp_fr = _make_nlp(
            {
                msg_user: [("Marie", "PER", 0, 5), ("Jean", "PER", 16, 20)],
                msg_asst: [("Jean", "PER", 0, 4)],
            }
        )
        messages = [
            {"role": "system", "content": "Contexte RP."},
            {"role": "user", "content": msg_user},
            {"role": "assistant", "content": msg_asst},
        ]
        with patch(f"{MODULE}._get_nlp_fr", return_value=nlp_fr), patch(
            f"{MODULE}._get_nlp_en", return_value=_make_nlp({})
        ), patch(f"{MODULE}._detect_lang", return_value="fr"):
            result = anonymize_session(messages)

        assert result[0]["content"] == "Contexte RP."
        assert result[1]["content"] == "[PER_1] demande à [PER_2] de l'aider."
        assert result[2]["content"] == "[PER_2] acquiesce."

    def test_english_batch_branch(self):
        msg_en = "Alice meets Bob."
        nlp_en = _make_nlp({msg_en: [("Alice", "PER", 0, 5), ("Bob", "PER", 12, 15)]})
        messages = [{"role": "user", "content": msg_en}]
        with patch(f"{MODULE}._get_nlp_fr", return_value=_make_nlp({})), patch(
            f"{MODULE}._get_nlp_en", return_value=nlp_en
        ), patch(f"{MODULE}._detect_lang", return_value="en"):
            result = anonymize_session(messages)
        assert result[0]["content"] == "[PER_1] meets [PER_2]."

    def test_mixed_language_counter_order(self):
        """Counter increments in original message order, not language-group order."""
        msg0_fr = "Marie parle."    # idx 0 — fr → PER_1 = Marie
        msg1_en = "Bob listens."    # idx 1 — en → PER_2 = Bob
        msg2_fr = "Jean répond."    # idx 2 — fr → PER_3 = Jean
        nlp_fr = _make_nlp(
            {msg0_fr: [("Marie", "PER", 0, 5)], msg2_fr: [("Jean", "PER", 0, 4)]}
        )
        nlp_en = _make_nlp({msg1_en: [("Bob", "PER", 0, 3)]})

        def fake_detect_lang(text: str) -> str:
            return "en" if text == msg1_en else "fr"

        messages = [
            {"role": "user", "content": msg0_fr},
            {"role": "user", "content": msg1_en},
            {"role": "user", "content": msg2_fr},
        ]
        with patch(f"{MODULE}._get_nlp_fr", return_value=nlp_fr), patch(
            f"{MODULE}._get_nlp_en", return_value=nlp_en
        ), patch(f"{MODULE}._detect_lang", side_effect=fake_detect_lang):
            result = anonymize_session(messages)

        assert result[0]["content"] == "[PER_1] parle."
        assert result[1]["content"] == "[PER_2] listens."
        assert result[2]["content"] == "[PER_3] répond."

    def test_system_message_untouched(self):
        messages = [{"role": "system", "content": "Instructions secrètes."}]
        result = anonymize_session(messages)
        assert result[0]["content"] == "Instructions secrètes."

    def test_extra_fields_preserved(self):
        text = "Bonjour."
        nlp_fr = _make_nlp({text: []})
        msg = {"role": "user", "content": text, "id": "abc123"}
        with patch(f"{MODULE}._get_nlp_fr", return_value=nlp_fr), patch(
            f"{MODULE}._get_nlp_en", return_value=_make_nlp({})
        ), patch(f"{MODULE}._detect_lang", return_value="fr"):
            result = anonymize_session([msg])
        assert result[0]["id"] == "abc123"


class TestNoEntity:
    def test_text_without_persons(self):
        text = "Le soleil se couche sur la forêt."
        nlp = _make_nlp({text: []})
        with patch(f"{MODULE}._nlp_for", return_value=nlp):
            mapping, counter = {}, [0]
            result = _replace_persons(text, mapping, counter)
        assert result == text
        assert counter[0] == 0

    def test_empty_content(self):
        messages = [{"role": "user", "content": ""}]
        result = anonymize_session(messages)
        assert result[0]["content"] == ""


class TestLangDetect:
    def test_detect_fr(self):
        with patch(f"{MODULE}.detect", return_value="fr"):
            assert _detect_lang("Bonjour le monde") == "fr"

    def test_detect_en(self):
        with patch(f"{MODULE}.detect", return_value="en"):
            assert _detect_lang("Hello world") == "en"

    def test_detect_unknown_falls_back_to_fr(self):
        with patch(f"{MODULE}.detect", return_value="de"):
            assert _detect_lang("Guten Tag") == "fr"

    def test_detect_exception_falls_back_to_fr(self):
        from langdetect import LangDetectException

        with patch(f"{MODULE}.detect", side_effect=LangDetectException(0, "")):
            assert _detect_lang("???") == "fr"
