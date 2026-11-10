# Security

This page documents security-*relevant implementation details as observed in
the source*. It does not certify the system as secure; it describes what
exists and, where relevant, what is absent.

## Authentication

- **Mechanism**: RS256-signed JWTs only. There is no HMAC/shared-secret mode,
  no API-key mode (despite `execution.yaml`'s `securityDefinitions` declaring
  `apiKey`-style `UserSecurity`/`AdminSecurity` — the actual implementation in
  `exec_api` is Bearer-JWT-based, not the `apiKey`-in-header scheme the spec
  describes; **the spec and the implementation disagree here**).
- **Verification point**: `exec_api` decorator (`image/execution_server.py`).
  For any route with `required_scopes` set (i.e. every route except
  `/health`):
  1. Requires an `Authorization` header of the exact form `Bearer <token>`
     (any other shape → `401`).
  2. `jwt.decode(jwt_token, public_pem, algorithms=['RS256'], options=jwt_options)`
     where `jwt_options` enables `verify_signature`, `verify_exp`, `verify_iat`
     and disables `verify_nbf`/`verify_aud`.
  3. Extracts `scopes` (list of strings, or list of `{"scope": ...}` dicts)
     and `username` from the decoded claims.
  4. `401` if the token's scope set does not intersect `required_scopes`.
  5. On any exception during decode (bad signature, expired, malformed),
     returns `401` with the exception's traceback text embedded in the JSON
     `message` field (`f'Invalid JWT token: {traceback.format_exc()}'`) —
     **note**: this includes a full Python traceback in the HTTP response
     body, which is a verbose-error-disclosure pattern worth being aware of
     when exposing this service beyond a trusted network.
- **`PUBLIC_PEM` has no default** (`os.environ.get('PUBLIC_PEM', '')` — empty
  string). An empty/invalid key makes `jwt.decode` fail for *every* request,
  so the service fails **closed** (no bypass) if this variable is unset, but
  it also means the service is non-functional for any authenticated route
  until configured — there is no fallback/insecure mode.

## Authorization (scopes)

Five scope strings appear in the codebase: `execute:wsts`, `execute:testbed`,
`execute:sit`, `execute:other`, `admin`. Every `/executions/...` route
requires membership in the four `execute:*` scopes (any one is sufficient —
it's a set intersection, not "all required"). Only `/logging` requires
`admin`. `/health` requires none. There is no per-execution or per-venue
authorization check beyond scope membership — any caller with an `execute:*`
scope can register/run/halt/switch **any** `execution_id`; the token does not
appear to be checked against the specific execution it's acting on anywhere
in `image/execution_server.py`.

## Token exchange: Ingenium token → venue token

`RunHandler.post` does not forward the caller's original JWT to the Venue
Service. Instead, on every `run` call it:
1. Deep-copies the already-decoded Ingenium token's claims
   (`copy.deepcopy(self.jwt_decoded)`).
2. Overwrites `exp`/`iat` for a 1-hour window.
3. Re-signs with `EXEC_VENUE_PRIVATE_PEM` (RS256) into a **new** JWT.
4. Stores this as `venue_token` in Redis; stores the original as `ing_token`.

This is a **local token-minting** pattern, not a call to an external
identity provider — the Execution Server itself holds the private key that
the Venue Service is expected to trust (`EXEC_VENUE_PUBLIC_PEM` on the venue
side, implied but not verifiable from this repository). The repository does
not document why two separate RSA key pairs (Ingenium vs. venue) are used
instead of one, but the effect is a trust boundary: compromising one key
pair does not directly compromise the other.

## Token refresh trusts its own prior signature, not the presented token's

`refresh_ingenium_token()`/`refresh_venue_tokens()` call
`decode_ingenium_token(verify=False)`/`decode_venue_token(verify=False)`
before re-signing. With PyJWT, `verify_signature=False` also suppresses the
other claim checks (`exp`/`iat`/etc.) in the same `options` dict — i.e. this
decode step performs **no cryptographic or expiry validation** of the token
it's about to re-sign; it simply reads the payload. This is intentional (the
comment in the source explains it exists "so that we can renew an expired
token when the previous step took a long time" — long-running steps can
outlive a 30-minute/1-hour token window), and the token being refreshed was
itself either verified at the `exec_api` boundary or minted by this same
server moments earlier — but it does mean the refresh path itself does not
re-authenticate the caller. If `PRIVATE_PEM`/`EXEC_VENUE_PRIVATE_PEM` were
ever exposed, so would be the ability to mint arbitrary refreshed tokens with
attacker-chosen unverified claims.

## TLS / transport

- `execution.yaml` declares `schemes: [http]` — plaintext HTTP for the
  Execution Server's own API is what the spec documents; nothing in
  `image/execution_server.py` configures TLS termination (no
  `ssl_options` passed to `tornado.httpserver.HTTPServer`).
- `ingenium_config.ssl_verify = False` is **hardcoded** and used as the
  `verify=` argument on every outbound `requests.get/post/...` call to the
  Venue Service from `ingenium_library.py` (e.g. `RealtimeEHA`, `CommandFSW`,
  `ChillEVRQuery`). **Outbound TLS certificate verification is disabled for
  all Venue Service calls**, unconditionally — there is no environment
  variable to turn it on.
- `image/ingenium_embedded/ingenium_step_sdk.py` (the unused standalone
  login helper) also passes `verify=False` on its own requests.

## Secrets handling

- JWT keys (`PUBLIC_PEM`, `PRIVATE_PEM`, `EXEC_VENUE_PRIVATE_PEM`,
  `EXEC_VENUE_PUBLIC_PEM`) are supplied as raw PEM text in environment
  variables — not file paths, not a secrets-manager SDK call.
- `.gitignore` excludes `*.pem`, implying key material is expected to be
  provided at deploy time rather than committed, but the repository itself
  contains no secret-provisioning tooling (no Vault/SSM/Secrets Manager
  integration code).
- `tests/unit/ingenium_embedded/test_token_auth.py` generates ephemeral RSA
  key pairs in-process for tests — no real key material is present in the
  repository.

## Input validation

Validation is implemented **per step module**, ad hoc, rather than via a
shared schema-validation layer:
- `custom_script_step.run` explicitly checks `script_name`/`hash`/`script_path`
  are present before proceeding (`get_dict_value_default_none`).
- `manual_input_step.cast_actual_value` wraps `int()`/`float()` conversions in
  `try/except`, raising `StepExecutionError` with a `USER_INPUT_ERROR` on
  failure.
- `check_config_step.run` validates `verification_condition` ∈
  `{EQUAL, NOT_EQUAL}` and `field_name` ∈ `{TYPE, STATUS, SERIAL}` before
  querying the venue.
- `run_eha_verification` rejects empty `entries` lists and missing
  `data_path`/`channel_id` per entry.

There is no top-level JSON-schema validation of the inbound `Step` body
against `execution.yaml`'s `Step` definition — malformed input generally
surfaces as an uncaught `KeyError`/`TypeError` inside a step module, caught
by the broad `except:` in `RunHandler.post` and returned as a `200` with
`status: ERROR` (see [Error Handling](Error-handling.md)), or, for
handler-level JSON body parsing failures, a `400` from `ExecutionHandler.put`.

## Server-side value parsing

`ConfigHandler.get` calls `ast.literal_eval(run_response)` on the string
value read back from Redis (originally written by `ExecutionHandler.put`
from caller-supplied `VenueInfo` fields, or elsewhere by step code). Compared
to `eval()`, `ast.literal_eval` cannot execute arbitrary code — it only
parses Python literal structures (strings, numbers, tuples, lists, dicts,
booleans, `None`) — but it will still raise (caught, surfaced as a `400`) on
any value that isn't a Python literal.

## Security boundaries not addressed by this repository

The repository does not document or implement, as far as the source shows:
- Rate limiting or request throttling.
- CORS configuration (no `Access-Control-*` headers or Tornado CORS settings
  are set anywhere in `execution_server.py`).
- Tornado XSRF cookie protection (`xsrf_cookies` is not enabled in
  `settings`).
- Per-execution ownership checks (see Authorization above).
- Audit logging beyond the structured request/step logs described in
  [Error Handling](Error-handling.md).
