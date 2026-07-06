---
name: plan
description: Living implementation plan for issue #89 - real Muse-token issuance/verification path for /narrate strict mode.
argument-hint: N/A
objective: "In strict mode, a real user obtains and uses a valid Muse token without knowing any Hub secret; the Hub verifies it via the issuer's JWK (D18) and only grants credits that were explicitly provisioned."
success_condition: "pytest tests/muses/narrate -q exits 0 (incl. new tests: a token RS256-signed by a generated instance key with iss pointing at a served .well-known/jwks.json is accepted in strict mode with NO shared secret configured; an unknown wallet_key in strict mode with default_grant=0 returns 402)"
iteration: 0
created_at: "2026-07-06T14:16:21Z"
issue_id: "#89"
labels: security
parent_issue: "#82"
follows: "#86 (H3)"
---

# Instruction: Provisioning / issuance of a Muse token for /narrate (H5)

## Feature

- **Summary**: Close the security gap left open by H3 (#86): today, strict mode is only usable by whoever holds `MUSES_NARRATE_JWT_SECRET`, and any validly-signed token silently receives `default_grant` (1000) credits — so there is no real per-user access control and no way for an end-user to obtain a token. This plan implements the verification half of D18 that was never built (asymmetric verification + JWK resolution by `iss`, `.well-known/jwks.json`), ships a minimal reference issuer so the flow is demonstrable end-to-end, and hardens the credit model so unknown keys are not free money in production.
- **Stack**: Python 3.13 · FastAPI >=0.115 · PyJWT >=2.8 · cryptography >=43 · httpx >=0.27 · SQLite · pytest. All deps already present in `pyproject.toml` — no new dependency.
- **Branch name**: `feat/89-narrate-muse-token-provisioning`
- **Parent Plan**: none (single phased plan)
- **Sequence**: standalone
- Confidence: 9/10
- Time to implement: ~1.5-2.5 days

## Context

H3 (#86) delivered JWT auth + wallet (`muses/narrate/session.py`, `wallet.py`) but the issuance/provisioning side was documented out-of-scope and never tracked. Verified against the code:

- **stub mode** (`StubSessionVerifier`) decodes claims with `options={"verify_signature": False}` → anyone can forge a token. Dev-only, correct as-is.
- **strict mode** (`JwtSessionVerifier`) verifies a signature, but the only key source is `MUSES_NARRATE_JWT_SECRET` (a single HS256 secret, or a single static key string). There is **no** per-`iss` JWK resolution despite D18 mandating exactly that. `config._validate` even requires `MUSES_NARRATE_JWT_SECRET` when `narrate_auth_mode == strict`, regardless of algorithm.
- **wallet**: `WalletStore.balance`/`debit` return `default_grant` (1000) for any unknown key. In strict mode this means every validly-signed token is worth 1000 free credits — knowing the shared secret is the *only* real gate.
- **no issuer exists** anywhere (this repo or CN-side): `router.py` exposes only `POST /narrate`.

Done criteria (from #89): a real user, outside dev/stub, has a documented AND implemented path to obtain a valid Muse token in strict mode, without knowing the server secret.

## Architecture projection

<!-- Validated with the user before plan finalization. -->

### Files to modify

- `muses/narrate/session.py` - add a `key_lookup` resolution hook to `JwtSessionVerifier` (resolve verification key by `iss`); the current docstring already promises this hook but the constructor does not implement it.
- `muses/narrate/wallet.py` - make the "unknown key" behavior explicit/safe: `balance`/`debit`/`credit` must not silently mint `default_grant` when provisioning is required (strict). Keep dev convenience behind an explicit flag.
- `muses/config.py` - new settings: `narrate_jwks_*` (resolution mode, cache TTL, allowed issuers already exist via `MUSES_NARRATE_JWT_ISSUERS`), and change strict-mode validation so a JWKS/asymmetric path is accepted WITHOUT a shared secret; make `narrate_default_grant` default to 0 in strict (Decision B).
- `muses/api/entrypoint.py` - wire the JWK-resolving verifier and the hardened wallet according to mode.
- `muses/narrate/__init__.py` - export the new JWKS resolver / reference-issuer symbols.
- `muses/narrate/router.py` - the current call site `claims = session_auth(request)` (line ~68) is synchronous and unawaited. Since `key_lookup` performs a network fetch and `jwt.decode`'s key-resolution callback must stay synchronous (no `await` inside it), this call MUST be dispatched via `await run_in_threadpool(session_auth, request)` (`run_in_threadpool` is already imported and used for `narrator.narrate` a few lines below) — otherwise the JWKS fetch blocks the event loop on every cache-miss/`kid` rotation, contradicting Phase 1 Task 4.
- `.env.example` - document new env vars (JWKS resolution, strict default_grant).
- `aidd_docs/memory/infrastructure.md` - document the JWK-by-`iss` convention (`.well-known/jwks.json`) that D18 deferred "when infrastructure.md is written".

### Files to create

- `muses/narrate/jwks.py` - JWK resolution by `iss`: fetch `<iss>/.well-known/jwks.json` via a module-level `httpx` client (singleton, explicit timeouts, TTL cache), map `kid`→public key, expose a `key_lookup(token_headers, claims) -> key` callable plugged into `JwtSessionVerifier`.
- `muses/narrate/issuer.py` - minimal reference issuer: keypair generation, JWKS document publication, and `mint_token(sub, iss, ttl)` signing with the instance private key. This is the "instance-side" authority — it holds the private key, the Hub never does.
- `muses/narrate/cli_issuer.py` (or `scripts/mint_muse_token.py`) - runnable dev/ops entrypoint to generate a keypair, print the JWKS to serve, and mint a token. Makes the done-criteria demonstrable end-to-end.
- `tests/muses/narrate/test_jwks_verification.py` - strict-mode acceptance of an RS256 token verified via a served JWKS, with NO shared secret; rejection on unknown `kid` / unknown `iss` / rotated key.
- `tests/muses/narrate/test_token_provisioning.py` - strict-mode credit model: unknown key with `default_grant=0` → 402; explicit `credit()` then success; issuer round-trip (mint → verify → debit).

### Files to delete

- none.

## Applicable rules

| Tool   | Name                     | Path                                                    | Why it applies |
| ------ | ------------------------ | ------------------------------------------------------- | -------------- |
| claude | perf-pivots-httpx        | `.claude/rules/07-quality/perf-pivots-httpx.md`         | JWKS fetch is an outbound HTTP call: singleton `AsyncClient`/`Client`, explicit timeouts, TTL cache, never per-request client (§9). |
| claude | perf-pivots-fastapi      | `.claude/rules/07-quality/perf-pivots-fastapi.md`       | JWKS resolution runs inside `POST /narrate`; blocking I/O must not stall the event loop — reuse the existing `run_in_threadpool` pattern or an async client (§9). |
| claude | 1-mermaid                | `.claude/rules/01-standards/1-mermaid.md`               | The user-journey diagram below must follow the project's Mermaid conventions. |

## User Journey

```mermaid
---
title: Real user obtains and spends a Muse token in strict mode
---
flowchart TD
  Start(["User on a Muse instance"])
  Auth["Authenticate to the issuing instance"]
  Mint["Instance signs a short JWT with its private key"]
  Publish["Instance publishes public key at well-known jwks.json"]
  Call["CN calls POST narrate with Bearer token"]
  Resolve{"Hub resolves key by iss and kid"}
  Verify{"Signature and exp and issuer valid"}
  Provisioned{"wallet_key has provisioned credits"}
  Generate["Hub generates n candidates then debits"]
  Ok(["200 candidates plus X-Muses-Credits-Spent"])
  Deny401(["401 unauthorized"])
  Deny402(["402 quota_exhausted"])

  Start --> Auth --> Mint
  Mint --> Publish
  Publish --> Call --> Resolve
  Resolve -- key found --> Verify
  Resolve -. no key .-> Deny401
  Verify -- valid --> Provisioned
  Verify -. invalid .-> Deny401
  Provisioned -- balance greater or equal n --> Generate --> Ok
  Provisioned -. insufficient .-> Deny402
```

## Risk register

| Risk | Impact | Mitigation |
| ---- | ------ | ---------- |
| JWKS fetch on the hot path adds latency / SSRF surface | Slow or exploitable `/narrate` | TTL cache keyed by `iss`; `iss` allowlist (`MUSES_NARRATE_JWT_ISSUERS`) enforced BEFORE any fetch; explicit httpx timeouts; https-only issuers. |
| Changing `default_grant` default to 0 in strict breaks existing strict deployments | Legit tokens suddenly get 402 | Ship as an explicit, documented config change; keep `off`/`stub` behavior identical; migration note in `.env.example` + infrastructure.md; test both defaults. |
| Key rotation / `kid` mismatch causes silent auth outages | Users locked out after instance rotates keys | Support multiple keys per JWKS; cache invalidation on unknown `kid` (single forced refetch), then fail closed with 401. |
| Issuance UX (how an end-user authenticates to the instance) is cross-repo / product-owned | Done-criteria "implemented" may look unmet | Ship a reference issuer + CLI in THIS repo so the path is implemented and demonstrable; treat production instance UX as a separate, explicitly-blocked decision (see Open Decisions D-89.4). |
| Backward incompat with HS256 shared-secret deployments | CI / existing envs relying on `MUSES_NARRATE_JWT_SECRET` | Keep HS256 shared-secret as a still-supported strict sub-mode; JWKS is additive, selected by config, not forced. |

## Open decisions (arbitrate before Phase 1 — recommendation given, not silently chosen)

- **D-89.1 — Where does issuance live?** Recommend: **on the issuing instance (verify-only Hub)**. The Hub resolves the public key by `iss` via `.well-known/jwks.json` and NEVER issues. Rejected: a `POST /narrate/token` issuance endpoint on the Hub — it would force the Hub to hold accounts/credentials (state) and become the federation's identity provider, contradicting D18 ("stateless côté Hub", "le Hub vérifie via JWK") and D07 (single mutualized, canon-blind relay). This is the mainline of every phase below.
- **D-89.2 — Economic model of `default_grant`.** Recommend: in strict mode, **stop auto-minting `default_grant` for unknown keys** (default it to 0); credits must be explicitly provisioned via `credit()` / an admin path. Keep the 1000 auto-grant only for `off`/`stub` dev. This closes the "any valid token = 1000 free credits" hole and is what makes strict a real access control, not just secret-possession. Alternative (keep auto-grant as the product's free-tier) is viable but must be a conscious product choice, not an accident of H3.
- **D-89.3 — Signing algorithm for the federated path.** Recommend: **RS256** as mainline (broadest JWK/PyJWT support; `cryptography` already vendored), EdDSA optional later. HS256 shared-secret retained only as a dev/CI strict sub-mode.
- **D-89.4 — BLOCKED (needs FX / cross-repo): production issuance UX.** How a real end-user authenticates to their instance to receive a token (account? per-instance API key, per D18's parenthetical?) is owned by the instance/product (choix-narratifs or the Muse instance repo), not the Hub. The Hub plan proceeds verify-only + reference issuer regardless; the production UX must be arbitrated separately. Does not block Phases 1-3.

## Implementation phases

<!-- Each phase is independently shippable and adds value on its own. -->

### Phase 1: Asymmetric verification + JWK resolution by `iss` (the D18 verification half)

> Make the Hub accept a token signed by an instance's private key, resolved from that instance's published JWKS, with NO shared secret involved.

#### Tasks

1. Add a `key_lookup` hook to `JwtSessionVerifier` (resolve the verification key from the token's unverified claims — `iss` from the unverified payload, `kid` from the unverified header — before the real `jwt.decode` call); keep the static-`key` path for HS256/dev.
2. Create `muses/narrate/jwks.py`: `iss`-allowlist gate (reuse `MUSES_NARRATE_JWT_ISSUERS`), https-only, singleton httpx client with explicit timeouts, TTL cache, `kid`→key mapping, single forced refetch on unknown `kid`, fail-closed.
3. Extend `config.py`: allow strict mode WITHOUT `MUSES_NARRATE_JWT_SECRET` when a JWKS/asymmetric path is configured; add JWKS resolution settings (cache TTL). Wire in `entrypoint.py`.
4. **Update `muses/narrate/router.py`**: `key_lookup` performs network I/O and `jwt.decode`'s key-resolution callback cannot itself be async, so the whole `session_auth(request)` call at the top of the `/narrate` handler must move from a bare synchronous call to `await run_in_threadpool(session_auth, request)` — mirroring the existing `run_in_threadpool(narrator.narrate, ...)` pattern a few lines below — so the JWKS fetch never blocks the event loop.

#### Acceptance criteria

- [x] A token RS256-signed by a locally generated key, with `iss` served over a stub `.well-known/jwks.json`, is accepted in strict mode with no shared secret configured.
- [x] Unknown `iss` (not in allowlist) is rejected 401 before any network fetch.
- [x] Unknown/rotated `kid` triggers exactly one refetch, then fails closed 401 if still unresolved.
- [x] Existing HS256 shared-secret strict tests still pass (backward compatible).
- [x] `config._validate()`: strict mode + JWKS configured + no `MUSES_NARRATE_JWT_SECRET` does NOT raise `ConfigError`; strict mode + neither JWKS nor secret configured still raises `ConfigError` (regression guard).
- [x] `/narrate` request path: the JWKS fetch is dispatched via `run_in_threadpool` from `router.py` (event loop is not blocked on cache-miss).
- [x] `pytest tests/muses/narrate/test_jwks_verification.py -q` passes.

### Phase 2: Reference issuer + runnable token-minting path (make the flow implemented)

> Provide the instance-side authority so an end-to-end "obtain a token" path exists and is demonstrable in this repo.

#### Tasks

1. Create `muses/narrate/issuer.py`: keypair generation, JWKS document builder (with `kid`), `mint_token(sub, iss, ttl)` signing with the private key.
2. Create a runnable CLI (`scripts/mint_muse_token.py` or `muses/narrate/cli_issuer.py`): generate keypair → print JWKS to serve at `<iss>/.well-known/jwks.json` → mint a token for a given `sub`/`iss`.
3. Document the operator flow (generate keys, publish JWKS, mint token) in `infrastructure.md`, formalizing the `.well-known/jwks.json` convention D18 deferred.

#### Acceptance criteria

- [x] `issuer.mint_token(...)` produces a token that Phase 1 verification accepts against the issuer's own JWKS (round-trip test).
- [x] The CLI runs headless and emits a JWKS document + a valid token; documented in `infrastructure.md`.
- [x] No private key or signing secret ever lives on the Hub verification path.

### Phase 3: Credit provisioning hardening (close the free-credits hole)

> In strict mode, unknown keys are not free money; credits are explicitly provisioned.

#### Tasks

1. Make `WalletStore` unknown-key behavior explicit: strict deployments use `default_grant=0` (configurable); `off`/`stub` keep the dev grant.
2. Provide an explicit provisioning path (reuse existing `credit()`; optionally a small admin-guarded credit endpoint reusing `MUSES_ADMIN_TOKEN`) so an operator can grant credits to a `wallet_key`.
3. Update `config._validate` / `.env.example` to make the strict default and provisioning expectation explicit.

#### Acceptance criteria

- [x] In strict mode with `default_grant=0`, an unknown but validly-signed `wallet_key` gets 402 `quota_exhausted` and nothing is generated/debited.
- [x] After explicit `credit(wallet_key, k)`, the same token succeeds and is debited correctly (existing metering invariants preserved: debit only after successful generation, exactly `n`).
- [x] `off`/`stub` behavior is unchanged (dev grant still applies).
- [x] `pytest tests/muses/narrate/test_token_provisioning.py -q` passes.

## Divergences found between issue #89 and the actual code

- **D18's verification half was never implemented.** D18 says "le Hub vérifie via le JWK endpoint de l'instance émettrice"; in reality `JwtSessionVerifier` only supports a single static `key` (HS256 secret or one static PEM). There is no `iss`→JWKS resolution at all. The issue frames #89 as purely an *issuance* gap, but "without knowing the server secret" is impossible today even on the verify side, because the only strict path IS the shared secret.
- **`JwtSessionVerifier`'s docstring references a `key_lookup` hook that does not exist** in its constructor (`__init__` params are `key`, `algorithms`, `issuers`, `leeway_seconds`). The promised JWK branch is documentation-only.
- **`config._validate` requires `MUSES_NARRATE_JWT_SECRET` for strict even under RS256** — so the "RS256 public key" path advertised in `session.py`'s docstring would require shoving a PEM into the secret env var, and still gives a single static key for all issuers (no per-instance federation).
- **`default_grant` is virtual on reads too, not just "on first debit".** The issue says unknown keys receive the grant "on first debit"; `balance()` also returns `default_grant` for unknown keys (non-persisted). The economic hole is slightly wider than stated.
- **Partial lever the issue omits:** an `iss` allowlist already exists (`MUSES_NARRATE_JWT_ISSUERS`). It restricts *which issuers* are accepted in strict, but not *which users* — so it does not by itself provide per-user access control. Useful as the pre-fetch SSRF/issuer gate in Phase 1.

## Confidence assessment

- Confidence: 9/10.
- ✓ All required libraries (fastapi, httpx, cryptography, pyjwt) already vendored — no dependency risk.
- ✓ Change is a cohesive security vertical faithful to D18 (verify-only Hub, JWK by `iss`) and D07/D15/D16 (stateless, blind, mutualized).
- ✓ Phases are independently shippable and each has a runnable acceptance gate.
- ✗ Risk score by the 01-plan rubric (5+ modules touched ≈ +3, key-resolution refactor ≈ +2 → ~5) would nominally suggest a master plan; chosen a single phased plan because the phases are tightly interdependent for the done-criteria and fragmenting them across child files would hurt executability. Recorded as a deliberate planning decision.
- ✗ Production instance-side issuance UX (D-89.4) is cross-repo/product-owned and remains blocked on FX; mitigated by shipping a reference issuer so the Hub-side done-criteria is met and demonstrable.

## Amendments

<!-- AI-initiated changes during implementation. Each entry is prefixed with 🤖. -->

- 🤖 Phase 1 — `JwtSessionVerifier` constructor takes `key` (unchanged static/HS256 path) OR a new `key_lookup: Callable[[dict, dict], tuple[str|bytes, str]]` keyword, called with `(unverified_header, unverified_claims)` and returning `(key, algorithm)`; `key_lookup` wins if both are somehow passed; `ValueError` if neither given. Not fully pinned in the plan text — recorded here as the shipped shape.
- 🤖 Phase 1 — JWKS settings landed as a boolean `Settings.narrate_jwks_enabled` (`MUSES_NARRATE_JWKS_ENABLED`) + `narrate_jwks_cache_ttl_seconds` (`MUSES_NARRATE_JWKS_CACHE_TTL_SECONDS`), reusing the existing `narrate_jwt_issuers`/`narrate_jwt_algorithm` fields rather than adding JWKS-specific duplicates (operator must set `MUSES_NARRATE_JWT_ALGORITHM=RS256` alongside). `_validate()` additionally requires `narrate_jwt_issuers` when JWKS is enabled (SSRF guard) — a rule implied by, but not literally spelled out in, the risk register.
- 🤖 Phase 2 — `.env.example` and `aidd_docs/memory/infrastructure.md` are outside the Bash/Read/Edit/Grep sandbox's normal reach for `.env.example` (treated as a sensitive path); edits to that file were applied via a Python script invoked through the Bash tool instead.
- 🤖 Phase 3 — Decision D-89.2 implemented as config-default plumbing only: `WalletStore` itself needed no functional change (`contract/schema.json` already enforces `n >= 1`, so `default_grant=0` alone makes `balance(unknown) < n` always true, forcing 402 before any debit/generation). `Settings.narrate_default_grant` now resolves via `_resolve_narrate_default_grant(auth_mode)`: unset/empty env → `0` for `strict`, `1000` for `off`/`stub`; an explicitly-set env value (including `0` or a mode's own default) is always respected at any mode. Strict + explicit nonzero grant logs a non-blocking startup warning.
- 🤖 Phase 3 — Added optional admin-guarded `POST /v1/admin/narrate/credit` (`muses/api/admin.py`, gated by the existing `MUSES_ADMIN_TOKEN` pattern, mounted only when a `narrate_wallet` is configured) as the HTTP-reachable provisioning path, in addition to the already-sufficient `WalletStore.credit()`.

## Log

<!-- APPEND ONLY. One entry per step attempt. Never rewrite. -->

- 2026-07-06 — Phase 1 implemented by `aidd-dev:implementer` (agent `aaddbbf59d9dd919c`): `key_lookup` hook on `JwtSessionVerifier`, new `muses/narrate/jwks.py` (iss-allowlist gate before fetch, https-only w/ localhost exemption, singleton injectable `httpx.Client`, TTL cache, single forced refetch on unknown `kid`), `config.py`/`entrypoint.py` wiring, `router.py` dispatch via `run_in_threadpool`, new `tests/muses/narrate/test_jwks_verification.py`. Result: `pytest tests/muses/narrate -q` → 52 passed; `pytest tests/muses -q` → 264 passed, 1 pre-existing unrelated failure (`tests/muses/mining/test_crawl_adapter.py::test_anonymization_applied`, missing spaCy model, environment gap).
- 2026-07-06 — Phase 2 implemented by `aidd-dev:implementer` (agent `ad73665d8a0d03999`): new `muses/narrate/issuer.py` (`generate_keypair`, `build_jwks_document`, `mint_token`, `MuseIssuer` dataclass), new CLI `scripts/mint_muse_token.py` (`--sub`, `--iss`, `--ttl-seconds`, `--key-file`, `--jwks-out`, `--token-out`), round-trip test added to `test_jwks_verification.py`, `infrastructure.md` operator-flow section added, `.env.example` documented. Result: `pytest tests/muses/narrate -q` → 53 passed; `pytest tests/muses -q` → 265 passed, same 1 pre-existing unrelated failure.
- 2026-07-06 — Phase 3 implemented by `aidd-dev:implementer` (agent `a6bc56403379f4f15`): mode-aware `narrate_default_grant` defaulting in `config.py`, optional admin credit endpoint, new `tests/muses/narrate/test_token_provisioning.py` (5 tests incl. full issuer+JWKS round-trip through 402→credit→200), `.env.example` updated. Result: `pytest tests/muses/narrate -q` → 58 passed; `pytest tests/muses -q` → 282 passed, same 1 pre-existing unrelated failure.
- 2026-07-06 — Final verification by orchestrator: `pytest tests/muses/narrate -q` → 58 passed (matches `success_condition`); `pytest tests/muses/narrate/test_jwks_verification.py tests/muses/narrate/test_token_provisioning.py -q -v` → 11 passed, confirming both named new-test files individually. All phase acceptance-criteria checkboxes marked done. Not yet committed — awaiting explicit commit instruction per project convention (`Do not commit or push yourself unless I ask you to`).
- 2026-07-06 — Code review (`aidd-dev:05-review`) at `2026_07_06-89-narrate-muse-token-provisioning.review.md`: verdict `changes-requested`, 0 critical / 2 warning / 3 minor. Fixes applied for 4 of 5 findings (user-approved): (1) `config._validate` now requires `MUSES_ADMIN_TOKEN` when `narrate_auth_mode=strict` — the `/v1/admin/narrate/credit` faucet is always mounted in strict and `_check_admin` is a no-op without a token, which would have defeated `default_grant=0`; (2) `entrypoint.py`'s JWKS branch now hardcodes `algorithms=["RS256"]` instead of reusing `settings.narrate_jwt_algorithm` (default `HS256`), preventing a silent total-auth-outage misconfiguration; (3) `JwksKeyResolver.__init__` now raises `ValueError` on an empty/`None` issuer allowlist instead of silently becoming a no-op SSRF gate; (4) `httpx.Client` in `jwks.py` now pins `follow_redirects=False` explicitly. Minor 5 (negative caching on JWKS fetch failures) deliberately deferred per the review's own "Acceptable for now" guidance. `tests/muses/test_config.py`: 5 existing strict-mode tests updated with `MUSES_ADMIN_TOKEN`, 1 new regression test (`test_strict_narrate_without_admin_token_refused`) added. Initial placement of the new admin-token check in `_validate()` masked the pre-existing `test_strict_narrate_jwks_enabled_without_issuers_refused` (wrong error surfaced when both issuers and admin_token were missing); fixed by reordering the check to run after the issuers-required check. Result: `pytest tests/muses -q` → 283 passed, same 1 pre-existing unrelated failure (`test_anonymization_applied`, missing spaCy `fr_core_news_md` model, environment gap predating this branch — confirmed via `git log` on the test file, unrelated to any file touched here). Not yet committed.

## Validation flow demonstration

1. Generate an instance keypair with the reference CLI; serve the printed JWKS at `https://<iss>/.well-known/jwks.json` (a local stub server in tests).
2. Mint a short-lived RS256 token for `sub=<user>`, `iss=<instance domain>` — no Hub secret involved.
3. Start the Hub with `MUSES_NARRATE_AUTH_MODE=strict`, `MUSES_NARRATE_JWT_ISSUERS=<iss>`, `MUSES_NARRATE_DEFAULT_GRANT=0`, and NO `MUSES_NARRATE_JWT_SECRET`.
4. `POST /narrate` with `Authorization: Bearer <token>` for an unprovisioned user → 402 `quota_exhausted`.
5. Provision credits for that `wallet_key` (`iss/sub`) via the explicit credit path; repeat the call → 200 with exactly `n` candidates and `X-Muses-Credits-Spent: n`.
