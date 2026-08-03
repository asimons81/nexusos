# NexusOS F-02 Sign-Off Pack — Serve Hardening (Host-header / DNS-rebinding exfil)

**Commit:** `8687fbf` — "fix: harden serve against Host-header / DNS-rebinding exfil (F-02)"
**Prepared for:** Tony's review (review deliverable only — NOT an approval) · **Date:** 2026-08-02

## What changed and why it matters

`nexusos serve` previously bound loopback with no Host validation and no auth on `/api/*`,
so a hostile web page using DNS rebinding could make the browser resolve an attacker domain
to 127.0.0.1 and read the full indexed document text. F-02 closes that hole with a
loopback Host allowlist, a per-process API token, and Origin enforcement — all verified
here live over raw sockets.

## The 6 protections

| # | Protection | Implementation | Live probe result |
|---|------------|----------------|-------------------|
| 1 | Host allowlist (loopback only: `127.0.0.1` / `localhost` / `[::1]`) | `_ALLOWED_HOSTS`, `_host_allowed()` on every request | foreign Host → **403** |
| 2 | Duplicate-Host header rejection (RFC 7230 §5.4) | `get_all("Host")` length must be exactly 1 | duplicate Host → **400** |
| 3 | `X-NexusOS-Token` required on `/api/*` | `secrets.token_urlsafe(32)`, `compare_digest` | missing/wrong token → **403** |
| 4 | Foreign-Origin rejection (even with valid token) | `_origin_is_loopback()` on `Origin` | foreign Origin → **403** |
| 5 | CLI token print + non-loopback warning | token echoed at startup (stdout flushed); loud warning on `--host` non-loopback | token printed in server log |
| 6 | IPv6 bracket strictness in Host parsing | malformed `[::1` / `[::1]evil` never match allowlist | `[::1]evil` Host → **403** |

## Live verification (raw sockets, real responses, 2026-08-02)

Server: `nexusos serve --transport http --workspace /tmp/f02_probe_ws --host 127.0.0.1 --port 19889`
Startup output (real): `Serving NexusOS kernel data on http://127.0.0.1:19889` / `API token: vVN9...  # send as X-NexusOS-Token on /api/* requests`

| Probe | Expected | Actual |
|-------|----------|--------|
| GET /api/status, valid Host + token | 200 | `HTTP/1.0 200 OK` |
| GET /api/status, duplicate Host headers | 400 | `HTTP/1.0 400 Bad Request` — `"exactly one Host header is required"` |
| GET /api/status, Host: evil.example.com | 403 | `HTTP/1.0 403 Forbidden` — `"invalid or missing Host header"` |
| GET /api/status, Host: `[::1]evil` | 403 | `HTTP/1.0 403 Forbidden` |
| GET /api/status, no token | 403 | `HTTP/1.0 403 Forbidden` — `"missing or invalid X-NexusOS-Token"` |
| GET /api/status, wrong token | 403 | `HTTP/1.0 403 Forbidden` |
| GET /api/status, valid token + `Origin: https://evil.example.com` | 403 | `HTTP/1.0 403 Forbidden` — `"cross-origin requests are not allowed"` |
| GET /api/status, valid token + loopback Origin | 200 | `HTTP/1.0 200 OK` |
| GET /healthz, no token | 200 | `HTTP/1.0 200 OK` (health check stays open) |
| GET /api/documents, valid token | 200 + JSON | `200 OK`, documents array, `Cache-Control: no-store` |

## Regression tests (all green)

`tests/unit/test_serve_security.py` — 17 tests, e.g. `test_dns_rebinding_host_header_rejected`,
`test_api_documents_requires_token`, `test_api_rejects_foreign_origin_even_with_valid_token`,
`test_duplicate_host_headers_rejected`, `test_malformed_ipv6_bracket_host_rejected_live`,
`test_root_page_injects_api_token`, `test_healthz_open_without_token`.
Also: `tests/integration/test_lint_serve_cli.py::test_serve_non_loopback_host_warns`.
Security suite: **17/17 passed**. Full gate re-run on main: PASS (ruff check clean, format clean, mypy clean, **414 pytest passed**).

## Verdict for Tony

1. F-02 is real and effective — every claimed protection reproduced live over raw sockets with
   the exact expected status codes (400/403/403/403/403/403/200/200), and error bodies are precise.
2. The design is sound for a loopback data server: token is per-process and timing-safe
   (`compare_digest`), healthz stays open for supervisors, UI keeps working via token injection,
   and non-loopback binds carry an explicit warning.
3. Ready for your go: this pack is the review artifact for F-02; release remains blocked on your
   explicit approval (card t_c0309ac6).
