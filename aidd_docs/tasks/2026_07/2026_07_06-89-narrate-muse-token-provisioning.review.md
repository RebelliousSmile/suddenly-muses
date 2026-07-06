---
name: review-code
description: Code review report for issue #89 — Muse-token issuance/verification path for /narrate strict mode
argument-hint: N/A
---

# Code Review: #89 — Muse-token provisioning (strict-mode JWK verification half of D18)

Security vertical is correct at its core (crypto path, SSRF gate ordering, fail-closed, threadpool dispatch all verified); findings are config-hardening gaps that fail *closed* but can silently brick or under-protect a strict deployment.

- **Verdict**: changes-requested
- **Diff scope**: working tree vs `main` (89ca1e5) — branch `feat/89-narrate-muse-token-provisioning`, uncommitted
- **Date**: 2026_07_06
- **Findings**: 0 critical, 2 warning, 3 minor

Verdict: `approve` = no critical findings, ship it; `changes-requested` = warnings or a fixable critical to address first; `blocked` = a critical that must not merge.

## Expected changes

From the plan (Phases 1–3, acceptance criteria):

- [x] Asymmetric verification + JWK resolution by `iss` (`key_lookup` hook on `JwtSessionVerifier`, new `jwks.py`).
- [x] `iss` allowlist enforced BEFORE any network fetch (SSRF gate); https-only except localhost.
- [x] Unknown/rotated `kid` triggers exactly one forced refetch, then fails closed 401.
- [x] `config._validate`: strict + JWKS (no shared secret) OK; strict + neither → `ConfigError`; JWKS enabled → issuers required.
- [x] `/narrate` dispatches `session_auth` via `run_in_threadpool` (event loop not blocked on cache-miss).
- [x] Reference issuer (`issuer.py`) + CLI (`scripts/mint_muse_token.py`); Hub never holds a private key.
- [x] Strict `default_grant` defaults to 0 (unknown key → 402), explicit provisioning via `credit()` / admin endpoint.

All planned behaviors are present. The gaps below are on the *configuration/wiring* edges, not the happy path.

## Findings

| Sev | Category | Location | Issue | Suggested fix |
| --- | -------- | -------- | ----- | ------------- |
| 🟡 | security | `muses/api/admin.py:115-122` (+ `muses/api/server.py:443`) | The new `POST /v1/admin/narrate/credit` faucet reuses `_check_admin`, which is a **no-op when `admin_token is None`**. The route is mounted whenever `narrate_wallet` exists (always, incl. strict). So a strict deployment that enables JWKS auth but leaves `MUSES_ADMIN_TOKEN` unset exposes an **open credit faucet**: anyone can mint credits for any `wallet_key`, defeating the exact `default_grant=0` access control this whole vertical adds. `/coverage` tolerating a no-op guard only leaks read-only data; this is a privileged write. No config rule ties `admin_token` to strict mode. | Require `admin_token` (`ConfigError`) when `narrate_auth_mode == "strict"` and a wallet is mounted; or fail-closed (403) on the credit route specifically when `admin_token is None`. |
| 🟡 | backend | `muses/api/entrypoint.py:57` (+ `muses/narrate/jwks.py:145`) | JWKS branch passes `algorithms=[settings.narrate_jwt_algorithm]` whose default is `"HS256"`, but `key_lookup` hardcodes returning `"RS256"`. If an operator sets `MUSES_NARRATE_JWKS_ENABLED=true` and forgets `MUSES_NARRATE_JWT_ALGORITHM=RS256`, `session.py:149` rejects every token (`algorithme 'RS256' non autorisé`) → **silent total auth outage**. Fails closed (safe) but bricks the feature with no config guard; tests miss it because they build the verifier with `algorithms=["RS256"]` directly, not via `entrypoint`. | In `config._validate`, when `narrate_jwks_enabled`, require/normalize `narrate_jwt_algorithm` to an asymmetric alg (RS256); or default the JWKS branch to `["RS256"]` instead of reusing the HS256 default. |
| 🟢 | security | `muses/narrate/jwks.py:79,86` | `JwksKeyResolver` treats empty/None `issuers` as "no allowlist" (`_check_allowlist` becomes a no-op → fetches any `iss`, SSRF). Currently guarded only by `config._validate` requiring issuers when JWKS is enabled — the resolver itself is not fail-closed if constructed directly. Defense-in-depth gap. | Raise in `__init__` (or `_check_allowlist`) if `issuers` is falsy — the resolver should refuse to run without an allowlist. |
| 🟢 | security | `muses/narrate/jwks.py:81` | JWKS fetch relies on httpx's implicit default `follow_redirects=False`. Safe today, but if a later change flips it, an allowlisted issuer could 3xx-redirect the fetch to an internal address (`169.254.169.254`, etc.) — SSRF past the allowlist. | Pin `follow_redirects=False` explicitly on the `httpx.Client(...)` construction to lock the invariant. |
| 🟢 | performance | `muses/narrate/jwks.py:117-124` | No negative caching: a down/unresolvable issuer triggers a live fetch on every request, and an unknown `kid` always forces a refetch even right after an empty document was cached. Bounded by the 5 s timeout, but under load could pressure the threadpool. | Acceptable for now; consider a short negative-TTL for fetch failures if `/narrate` traffic grows. |

## Coverage

- **Scanned**: SSRF gate ordering (allowlist-before-fetch ✓, https-before-GET ✓, redirect exposure), fail-closed behavior (all resolution errors → `HTTPException` 401, caught in `router.py:72` ✓), key-resolution correctness (algorithm pinned from resolver not token header → no alg-confusion attack ✓; verified `iss` re-checked against allowlist post-decode ✓; `require:[sub,iss,exp]` + exp/leeway enforced by the real decode ✓), `run_in_threadpool` dispatch (present, reads only headers, sync-safe ✓), config validation, credit/debit/balance semantics under `default_grant=0`, error-handling, httpx singleton thread-safety (thread-safe for requests; cache dict mutation unlocked but GIL-atomic → only redundant fetches).
- **Not applicable**: frontend, CSS/render path (JSON API), Mermaid (diagram in plan, not in code diff).

## Follow-up

- **Top fixes** (ranked, hand off to `aidd-dev:07-refactor`):
  1. 🟡 Tie `admin_token` to strict mode (or fail-closed the credit route) — the credit faucet must not be open in the mode whose whole purpose is access control (`admin.py` / `config._validate`).
  2. 🟡 Guard the JWKS/algorithm mismatch in `config._validate` (or default JWKS branch to RS256) so an operator can't silently brick auth (`entrypoint.py` / `config.py`).
  3. 🟢 Make `JwksKeyResolver` fail-closed on an empty allowlist (`jwks.py`).
  4. 🟢 Pin `follow_redirects=False` explicitly on the httpx client (`jwks.py`).
- **Notes**:
  - No exploitable bypass found. The critical JWT pitfall (algorithm confusion — using an RSA public key as an HMAC secret) is correctly avoided: the verification algorithm comes from the resolver (`"RS256"`), never from the attacker-controlled token header, and the resolved key is an RSA public-key object.
  - SSRF gate ordering is correct: `_check_allowlist(iss)` runs before `_keys_for_issuer` → `_fetch_keys`, and `_is_https_or_local` runs before the GET.
  - Both W1 and W2 are "fails safe" (open-faucet requires an explicit missing-secret misconfig; the algorithm mismatch denies rather than admits) — hence `changes-requested`, not `blocked`.
  - `run_in_threadpool(session_auth, request)` is correct: `session_auth` only reads `request.headers` synchronously; no body is consumed off-loop.
