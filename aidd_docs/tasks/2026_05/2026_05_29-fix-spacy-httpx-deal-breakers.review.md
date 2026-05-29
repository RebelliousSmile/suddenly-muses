# Code Review for fix/spacy-httpx-deal-breakers

## Main expected Changes

- [x] spaCy `disable=` per model — FR disables `morphologizer, parser, attribute_ruler, lemmatizer`; EN disables `tagger, parser, senter, attribute_ruler, lemmatizer`. `tok2vec` and `ner` preserved in both, so NER still functions. (`pipelines/anonymization/anonymize.py:17-31`)
- [x] `nlp.pipe()` batch with counter ordering preserved — docs precomputed per language via `pipe(batch_size=50)`, but `_replace_persons` is still invoked in original message order in the final loop, and persons iterated in entity order, so `[PER_N]` numbering matches the old sequential behaviour. (`anonymize.py:88-114`)
- [x] httpx module-level singleton — single `httpx.Client` with explicit `Timeout`/`Limits`, per-call `with httpx.Client(...)` removed, `/v1/models` body cached. (`apps/playground/app.py:25-28`, `224-252`)

All three intended changes are present and functionally correct. Findings below are quality/robustness issues, not regressions of the stated goals.

## Scoring

`[severity] [category]: file:line issue (suggestion)`

- [major] [style/lint] `apps/playground/app.py:30,37,38` — Module-level `_http_client` (lines 25-28) is inserted **between** the third-party imports and the first-party imports, pushing 3 imports below executable code. Triggers `E402 Module level import not at top of file` (×3, confirmed by `ruff check`). This is introduced by the diff. (Move `_http_client` definition below all imports, e.g. just before `GATEWAY_URL`.)
- [major] [resource management] `apps/playground/app.py:25-28` — The module-level `httpx.Client` is **never closed**. No `atexit.register(_http_client.close)`, no lifespan/teardown hook. The TCP pool leaks until interpreter exit. It is also instantiated unconditionally at import time, even when the Gateway tab is never opened. (Register an `atexit` close handler, or lazily create the client on first `_fetch_gateway` call.)
- [minor] [style/lint] `tests/pipelines/test_anonymize.py:32` — `for t, l, s, e in raw_ents` uses ambiguous variable name `l`. Triggers `E741 Ambiguous variable name: 'l'` (confirmed by `ruff check`). This is new code from the diff. (Rename `l` to `label`.)
- [minor] [error handling / dead code] `apps/playground/app.py:234` — `except (httpx.RequestError, httpx.HTTPStatusError)` lists `HTTPStatusError`, but `_http_client.get()` never calls `raise_for_status()`, so `HTTPStatusError` cannot be raised here. The branch is dead/misleading. Same dead `HTTPStatusError` appears at line 245. (Drop `HTTPStatusError` from both tuples, or actually call `resp.raise_for_status()` if non-2xx should be treated as failure.)
- [minor] [correctness] `apps/playground/app.py:229-233` — Response status code is never checked before caching `resp.text` as `models_resp_text`. A 4xx/5xx with a JSON error body is treated as success; `json.loads` may then parse an unexpected shape (handled defensively via `.get("data", [])`, so it degrades to "no adapters" silently rather than surfacing the HTTP error). (Consider gating the cache / adapter parse on `resp.status_code == 200`.)
- [minor] [test coverage] `tests/pipelines/test_anonymize.py:101-103,119-121` — Every `anonymize_session` test patches `_detect_lang` to return `"fr"` (or uses only system/empty messages). The EN `pipe()` branch (`anonymize.py:96-100`) and the **mixed FR/EN routing + cross-language counter ordering** — the central new logic — are never exercised. The `en` mock is always fed `{}`. (Add a test with one FR and one EN message asserting each is routed to the correct model and `[PER_N]` numbering stays in message order.)

## Code Quality Checklist

- Type hints (`X | None`, builtins, annotated publics): PASS — `Optional` removed in both files, `_nlp_fr/_nlp_en: ... | None`, `doc: Doc | None`, `models_resp_text: str | None`, generics `dict[int, Doc]`, `list[dict]`. Functions annotated.
- Error handling (specific exceptions, no bare except): PARTIAL — `_fetch_gateway` catches specific httpx/json exceptions (good improvement over `with`-per-call), but includes the unreachable `HTTPStatusError` (dead branch). Note `_run_completion:65` still uses bare `except Exception` — pre-existing, out of diff scope.
- Resource management (context managers for I/O): PARTIAL — moving off per-call `with httpx.Client(...)` to a pooled singleton is the right call for repeated requests, but the singleton lacks any close/teardown, so the resource is now leaked instead of scoped.
- Correctness / edge cases: PASS — empty/whitespace/non-str/system messages preserved; counter ordering preserved; `Doc` fallback to `_nlp_for` when `doc is None` keeps `_replace_persons` usable standalone. spaCy `disable` lists keep `tok2vec`+`ner`, so NER intact.
- Test quality (mocks, patch targets, assertions): PARTIAL — patch paths corrected to `pipelines.anonymization.anonymize`; `_make_nlp` mock now supports both `__call__` (via `side_effect`) and `.pipe()` (order-preserving generator), so the `zip(pairs, pipe(...))` ordering logic is genuinely exercised; `TestSessionCoherence` correctly patches `_get_nlp_fr`/`_get_nlp_en`. Assertions are meaningful. Gap: no mixed-language test (see finding above); `.pipe` mock ignores `batch_size` (acceptable for unit scope).
- Code health (no dead code, no unnecessary complexity): PARTIAL — dead `HTTPStatusError` branches; otherwise clean. `anonymize.py` passes ruff with no warnings; `Doc` import is used.

## Final Review

- Score: 7/10
- Feedback: The three stated objectives are correctly implemented and the existing 14 tests pass. The spaCy disable lists are safe for NER (tok2vec/ner retained, could not runtime-verify the models since `fr_core_news_md`/`en_core_web_md` are not installed in this env — verified by static reasoning only). The batching preserves counter semantics. The two material issues are (1) the new module-level `httpx.Client` introduces 3 `E402` lint errors by sitting between import groups and is never closed — a real resource leak, and (2) the headline batching/routing logic for English and mixed-language sessions has zero test coverage because every session test pins `_detect_lang` to French. Remaining findings are minor (one new `E741`, dead `HTTPStatusError` branches, unchecked HTTP status).
- Follow-up Actions:
  1. Move the `_http_client` definition below all imports and add `atexit.register(_http_client.close)` (or lazy-init). Fixes E402 ×3 + the leak.
  2. Rename `l` → `label` in `test_anonymize.py:32` to clear E741.
  3. Add a mixed FR/EN `anonymize_session` test asserting per-language model routing and cross-language `[PER_N]` ordering.
  4. Remove the unreachable `httpx.HTTPStatusError` from both `except` tuples in `_fetch_gateway`, or call `resp.raise_for_status()` and check status before caching `models_resp_text`.
  5. (Optional) Runtime-verify the EN/FR disable lists actually produce `ner` in `nlp.pipe_names` and emit `PER` ents, once the spaCy models are installed.
