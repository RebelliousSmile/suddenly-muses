# Functional Review for fix/spacy-httpx-deal-breakers

- Plan: aidd_docs/tasks/2026_05/2026_05_29-fix-spacy-httpx-deal-breakers.pending.md
- Diff scope: fix/spacy-httpx-deal-breakers vs main
- Date: 2026-05-29

## Verdict

PASS - All 11 acceptance criteria across the 3 phases are fulfilled. The test suite (`tests/pipelines/test_anonymize.py`) exits 0 with 14 passed. The spaCy `disable=` lists match the plan exactly (model-specific, `tok2vec` preserved), the batch path uses `nlp.pipe()` with original-index ordering for `[PER_N]` numbering, and the httpx client is a module-level singleton with 4-field `Timeout`, explicit `Limits`, a single `/v1/models` fetch reused for adapter coverage, and specific exception types. No deal-breakers remain.

## Scoring Matrix

| Criterion | Files | Status | Severity | Notes |
| --- | --- | --- | --- | --- |
| P1: `fr_core_news_md` `disable=["morphologizer", "parser", "attribute_ruler", "lemmatizer"]` (no tagger) | anonymize.py:17-20 | fulfilled | - | Exact match, no `tagger` (French model has none) |
| P1: `en_core_web_md` `disable=["tagger", "parser", "senter", "attribute_ruler", "lemmatizer"]` | anonymize.py:27-30 | fulfilled | - | Exact match |
| P1: `tok2vec` not in any disable list | anonymize.py:19,29 | fulfilled | - | Confirmed absent from both lists (feeds ner) |
| P1: tests exit 0 | tests/pipelines/test_anonymize.py | fulfilled | - | 14 passed in 2.74s |
| P2: `anonymize_session` calls `nlp.pipe()`, zero `nlp(text)` in batch path | anonymize.py:91-100 | fulfilled | - | `_get_nlp_fr().pipe(...)` and `_get_nlp_en().pipe(...)`, batch_size=50 |
| P2: `_replace_persons` accepts `doc: Doc` parameter | anonymize.py:46-51 | fulfilled | - | `doc: Doc \| None = None` with `_nlp_for` fallback (per amendment, keeps unit tests working) |
| P2: counter iterates `range(len(messages))` in original order | anonymize.py:103-114 | fulfilled | - | `for i, msg in enumerate(messages)`, pulls `docs[i]` |
| P2: tests exit 0 and `[PER_N]` matches fixtures | tests/pipelines/test_anonymize.py:107-108 | fulfilled | - | Cross-message coherence test asserts PER_1/PER_2 reuse across messages |
| P3: no `httpx.Client(` inside `_fetch_gateway` | app.py:224-252 | fulfilled | - | Only instantiation is module-level line 25; grep inside function returns 0 |
| P3: module-level `_http_client` with 4-field `Timeout` + `Limits` | app.py:25-28 | fulfilled | - | `Timeout(connect=5.0, read=10.0, write=5.0, pool=2.0)`, `Limits(max_connections=10, max_keepalive_connections=5)` |
| P3: `/v1/models` fetched once, JSON reused for adapter coverage | app.py:227-242 | fulfilled | - | `models_resp_text` captured in loop, reused via `json.loads` for adapters; no duplicate request |
| P3: `except Exception` replaced with specific httpx types | app.py:234,245 | fulfilled | - | Loop: `(httpx.RequestError, httpx.HTTPStatusError)`; adapter block: adds `json.JSONDecodeError` |

## Missing Behaviors

None. Every planned criterion has corresponding implementation.

## Unplanned Behaviors

- Two amendments were applied and documented in the plan (Phase 2):
  1. `_replace_persons` retained with `doc: Doc | None = None` and a `_nlp_for(text)` fallback instead of being deleted, so unit tests can call it in isolation. This is a sanctioned deviation, documented and coherent. The `nlp(text)` call at anonymize.py:55-56 only fires when `doc is None`, i.e. the standalone-test path — it is NOT in the `anonymize_session` batch path, so the "zero `nlp(text)` in the batch path" criterion holds.
  2. Test patch paths corrected from `pipeline.anonymize` to `pipelines.anonymization.anonymize`. Verified: tests now patch the real module (`MODULE = "pipelines.anonymization.anonymize"`) and pass.

## Flow / Edge-case Gaps

- Minor (non-blocking): the plan `success_condition` frontmatter references `tests/test_anonymize.py`, but the real path is `tests/pipelines/test_anonymize.py`. The amendment acknowledges the prior paths were wrong; the success_condition string itself was not updated. Cosmetic only — does not affect the implementation.
- The `_http_client` is module-level and never explicitly closed. Acceptable per the plan's risk register (Gradio full-process restart on reload). No connection-leak concern for the playground use case.
- Edge case handled correctly: when `/v1/models` fails, `models_resp_text` stays `None`, the adapter block raises a synthetic `httpx.RequestError` (app.py:240-241) caught by the specific-exception guard, producing a graceful message rather than crashing. Good defensive coverage.
- The `eligible` dict comprehension + two `zip()` passes over `fr_pairs`/`en_pairs` preserve per-language batch order, and final assignment re-iterates in original message order, so mixed-language sessions keep deterministic `[PER_N]` numbering. The `test_cross_message_coherence` fixture exercises exactly this and passes.

## Summary

completion_score: 100 (all 11 criteria reviewed, plus test execution and grep verification)
quality_score: 100 (plain-checklist validator; all criteria fulfilled, no findings above cosmetic severity)

The implementation faithfully realizes all three phases. The two deviations are explicitly documented amendments that preserve testability without compromising the batch-path criterion. The only observation is a stale `success_condition` path string in the plan frontmatter — cosmetic, no code impact. No blocking findings.
