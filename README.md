# actf — API Test Framework

YAML-driven API tests. **Adding a test = adding one `.yml` file.** No Python.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[test,allure]"

export AC_TOKEN=<your-api-key>
.venv/bin/python -m pytest tests/test_suites.py -q
```

---

## Writing a test

Drop a file in `suites/`. It is picked up automatically.

```yaml
name: Product then finding
tags: [smoke]
env: qa                            # -> env/qa.yml

auth: { type: bearer }             # token from AC_TOKEN

vars:
  productName: "apitest-${uuid}"   # unique per run

steps:
  - name: create product
    request:
      method: POST
      path: /api/product
      body: { name: "${productName}" }
    expect:
      status: 200
      assertions:
        - { path: "$.content.id", notNull: true }
    capture:
      productId: "$.content.id"    # -> ${productId} in every later step

  - name: seed finding into that product
    request:
      method: POST
      path: /api/finding
      body: { productId: "${productId}", severity: High }   # <- chained
    capture: { findingId: "$.content.id" }

  - name: verify SLA (async)
    request: { method: GET, path: "/api/finding/${findingId}" }
    retry: { until: pass, timeout: 30s, interval: 2s }
    expect:
      assertions:
        - { path: "$.content.slaDueDate", notNull: true }
        - { path: "$.content.tags", size: 2 }

cleanup:                           # always runs, reverse order
  - { request: { method: DELETE, path: "/api/product/${productId}" } }
```

### Chaining — capturing and passing values

`capture:` stores a value; `${name}` reads it in any later step — in the **path,
query, headers or body**, and inside assertion paths too. Captures accumulate
into one suite-wide context, so step 5 can use anything captured in steps 1–4.
Re-capturing the same name overwrites it.

**Types are preserved.** An integer id stays an integer in a JSON body; a
captured list stays a list. Only interpolation into a larger string stringifies.

#### Capturing multiple values

Capture as many as you like in one step — each key is a new variable:

```yaml
capture:
  productId: "$.data.id"                       # scalar
  owner:     "$.data.owner"                    # whole object
  tags:      "$.data.tags"                     # whole list
  itemIds:   "$.data.items[*].id"              # list of values -> [1,2,3]
  highIds:   "$.data.items[?(@.sev=='High')].id"   # filtered list
  firstItem: "$.data.items[0]"                 # one object out of a list
  teamId:    "$.data.owner.team.id"            # deep scalar
```

A path matching **many** nodes gives a list; matching **exactly one** gives the
value itself, not a one-element list.

Captures also work on non-JSON responses:

```yaml
capture:
  loc:  { from: header, path: location }
  code: { from: status, path: "-" }
```

#### Using captured values

```yaml
request:
  method: POST
  path: "/api/product/${productId}/link"     # scalar in the path
  query:   { team: "${teamId}" }             # in the query string
  headers: { X-Owner: "${owner.email}" }     # drill into a captured object
  body:
    ids:        "${itemIds}"                 # list passed through as a list
    owner:      "${owner}"                   # object passed through as an object
    ownerEmail: "${owner.email}"             # dotted access
    ownerTeam:  "${owner.team.name}"         # deep dotted access
    firstId:    "${firstItem.id}"            # object -> field
    firstTag:   "${tags[0]}"                 # list index
    lastTag:    "${tags[-1]}"                # negative index
    label:      "p-${productId}-t${teamId}"  # interpolated -> "p-42-t5"
```

| Form | Meaning |
|---|---|
| `${v}` | the captured value, original type |
| `${v.key}` | field of a captured object |
| `${v.a.b.c}` | nested field, any depth |
| `${v[0]}` / `${v[-1]}` | list element, negative allowed |
| `${v[0].id}` | mix indexes and keys freely |
| `"x-${v}"` | interpolated into a string |

And in assertions — including filtering by a captured value:

```yaml
- { path: "$.data.content[0].userId", eq: "${userId}" }
- { path: "$[?(@.email=='${testEmail}')].id", notNull: true }
```

A bad accessor fails loudly and lists what was available, rather than sending
`None`: `${owner.phone} — no key 'phone' at '.phone'. Available: email, team`.

See `tests/unit/test_capture_patterns.py` for a runnable example of every form.

### Placeholders

| Form | Result |
|---|---|
| `${productId}` | a captured value or suite `vars` entry |
| `${env:AC_TOKEN}` | environment variable (errors if unset) |
| `${env:X:-default}` | environment variable with a fallback |
| `${uuid}` | fresh UUID per call |
| `${now}` / `${now:%Y-%m-%d}` | UTC timestamp |
| `${randomInt:1,999}` | random integer |
| `${file:payloads/big.json}` | file contents, relative to the suite |

### Built-in matchers

`eq` `neq` `notNull` `isNull` `in` `notIn` `contains` `size` `matchesRegex`
`greaterThan` `lessThan` `isEmpty` `notEmpty` `type`

One matcher per assertion — two in one line is rejected at load time.

### Asserting on non-JSON

```yaml
- { from: header, path: Location, notNull: true }
- { from: status, eq: 201 }
- { from: body, contains: "signed-in successfully" }
```

### Arrays of objects

Most "pull props out of a list" cases are plain JSONPath:

```yaml
- { path: "$.content[*].asset.name",              eq: ["a1","a2","a3"] }
- { path: "$.content[?(@.sev=='High')].id",       eq: [1, 3] }
- { path: "$.content[*].asset.tags[*]",           contains: "x" }
- { path: "$..name",                              size: 3 }
```

⚠️ **Strict `>` / `<` in a filter is rejected at load time.** The default engine
(`jsonpath-ng`) truncates the comparand, so `?(@.score>7)` behaves as `>=8` and
silently drops `7.5` — a test that passes while proving nothing. Use an
inclusive bound, or the second engine:

```yaml
- { path: "$.content[?(@.score>=7.5)].id", eq: [1, 3] }              # default engine
- { from: jsonpath2, path: "$.content[?(@.score>7)].id", eq: [1,3] } # correct numerics
```

| Engine | Good at | Cannot do |
|---|---|---|
| `jsonpath` (default) | negative indexing, unions `[0,1]`, compound filters `&` | strict `>` `<` |
| `jsonpath2` | correct numeric comparison | negative indexing, unions, compound filters |

### When JSONPath isn't enough — the escape hatch

Like MapStruct's `default` method: when the declarative form runs out, drop to a
real function. Write it once, call it from any suite by name.

```python
# tests/test_suites.py
def high_score_asset_names(body, response):
    return [i["asset"]["name"] for i in body["content"] if i["score"] > 7]

def only_names(value):            # a `via:` post-processor
    return [v["name"] for v in value]

SuiteSession(..., functions={
    "highScoreAssetNames": high_score_asset_names,
    "onlyNames": only_names,
})
```

Two call forms:

```yaml
# 1. standalone — the function gets the whole body
- { from: fn, path: highScoreAssetNames, eq: ["a1", "a3"] }
capture:
  names: { from: fn, path: highScoreAssetNames }

# 2. via: — post-process whatever an extractor produced
- { path: "$.content[*].asset", via: onlyNames, size: 3 }
capture:
  names: { path: "$.content[*].asset", via: onlyNames }
```

Signatures are arity-detected — `fn(body)`, `fn(body, response)`, `via(value)`,
`via(value, body)`, `via(value, body, response)` all work.

#### Inline expressions (off by default)

```yaml
- { expr: "[i['id'] for i in body['content'] if i['score'] > 7]", eq: [1, 3] }
- { expr: "len(body['content'])", eq: 3 }
```

Enable with `SuiteSession(..., allow_inline=True)`. **Prefer named functions** —
a YAML file that executes arbitrary Python is one nobody can safely review. The
expression sees only `body`, `response`, `status`, `headers` and a small set of
builtins; `__import__`, `open` and friends are unreachable.

---

## Auth

| Type | How |
|---|---|
| `bearer` | **Recommended.** `AC_TOKEN` env var → `Authorization: Bearer <key>` |
| `password` | `POST /public/login`, carries the session cookie + `X-CSRF-TOKEN` |
| `none` | no auth |

**Why bearer is the default:** an API key bypasses session handling,
CSRF *and* TOTP. Password login returns a session cookie (not a JWT), and if the
tenant enforces TOTP it cannot complete unattended — the framework says so
explicitly rather than looping on 403s.

Auth resolves **once per suite** and is cached, so a login is not repeated per step.

Secrets never go in YAML. Use `${env:...}`, and note that everything attached to
an Allure report is masked (`Authorization`, `Cookie`, `password`, `token`, …).

---

## Extending — the only Java... sorry, Python you'll write

Three seams, identical shape. Pass instances to `SuiteSession` in
`tests/test_suites.py`; a custom one whose key matches a built-in replaces it.

```python
# a new matcher
class WithinDaysMatcher:
    key = "withinDays"
    def match(self, actual, expected):
        from actf import MatchResult
        delta = (parse(actual) - now()).days
        return MatchResult(0 <= delta <= expected, f"expected within {expected}d, got {delta}d")

SuiteSession(..., matchers=[WithinDaysMatcher()])
```

Then in YAML: `- { path: "$.slaDueDate", withinDays: 30 }`

Same for `extractors=[...]` (`key` + `extract(response, expr)`) and
`evaluators=[...]` (`prefix` + `evaluate(expr, ctx)`).

---

## Running

```bash
pytest tests/test_suites.py                          # everything
AC_TAGS=smoke pytest tests/test_suites.py            # only smoke-tagged
AC_ENV=preprod pytest tests/test_suites.py           # override the env
pytest tests/test_suites.py --alluredir=allure-results && allure serve allure-results
pytest tests/unit -q                                 # framework's own tests
```

Each suite is one Allure test; each step is an Allure step with the request and
response attached as JSON, secrets masked.

---

## Retry / polling

Many operations are eventually consistent — `DELETE /user/product/{id}`
returns 200 as soon as the job is *accepted*, and the product stays searchable
for a few seconds. Add `retry:` to any step that should be polled:

```yaml
- name: verify product no longer found
  request: { method: POST, path: /api/product, body: { name: ["${productName}"] } }
  retry: { until: pass, timeout: 60s, interval: 3s }
  expect:
    assertions:
      - { path: "$.data.totalElements", eq: 0 }
```

| Key | Default | Meaning |
|---|---|---|
| `timeout` | `30s` | wall-clock budget for the whole step |
| `interval` | `2s` | wait between attempts |
| `times` | unlimited | maximum number of attempts |
| `backoff` | `1` | multiply the interval each retry (`1` = fixed) |
| `maxInterval` | `30s` | cap on a growing interval |

`timeout` and `times` are independent — **whichever trips first wins**:

```yaml
retry: { times: 5, interval: 1s }                      # at most 5 attempts
retry: { timeout: 2m, interval: 5s }                   # poll for 2 minutes
retry: { times: 6, interval: 1s, backoff: 2 }          # 1s,2s,4s,8s,16s
retry: { times: 10, interval: 1s, backoff: 2, maxInterval: 10s }
```

Retries cover **connection failures too**, not just failed assertions, so a
flaky network blip does not fail an otherwise good run. The framework never
sleeps past the deadline just to fail immediately after, and the failure names
the limits it hit:

```
$.data.totalElements: expected 0, got 1
  (gave up after 5 attempts; limits: 60s, max 5 attempts, backoff x2)
```

## Logging

Every request and response is printed by default, with secrets masked:

```
━━━ SUITE  User lifecycle - create, search, delete

▶ STEP  create user
  → POST https://qa.example.com/user/add/user
  request body:
    { "email": "apitest-3f2a@example.com", "password": "***" }
  ← 200 142ms
  response body:
    {"id":42,"name":"API Test User"}
  ✓ PASS create user
  captured:
    { "userId": 42 }

▶ STEP  verify
  ← 401 88ms
  response body:
    {"message":"User is blocked or removed"}
  ✗ FAIL verify
    - status: expected 200, got 401
━━━ FAILED  1/2 steps passed
```

Configured by environment variables — no suite ever mentions logging:

| Variable | Default | Effect |
|---|---|---|
| `ACTF_LOG` | `info` | `debug` adds headers · `warn` = quiet until failure · `off` |
| `ACTF_LOG_FILE` | — | also append to this file (none written unless set) |
| `ACTF_LOG_BODY_LIMIT` | `4000` | truncate bodies over N chars |
| `ACTF_LOG_SECRETS` | off | `1` shows real tokens instead of `***` |
| `ACTF_LOG_COLOR` | auto | `0` disables ANSI (auto-off when not a tty) |

```bash
ACTF_LOG_FILE=run.log AC_TOKEN=… pytest tests/test_suites.py -m live   # to a file
ACTF_LOG=debug        AC_TOKEN=… pytest tests/test_suites.py -m live   # + headers
ACTF_LOG=warn         AC_TOKEN=… pytest tests/test_suites.py -m live   # CI-quiet
```

`Authorization`, `Cookie`, `password`, `token` and `apiKey` are masked in both
console and file, so a log is safe to paste into a ticket. The file never
contains ANSI colour codes. At `warn` a failing step still dumps its full
request and response — that is when you need them.

## TLS behind a corporate proxy

If every live suite fails with `CERTIFICATE_VERIFY_FAILED`, a TLS-inspecting
proxy (Zscaler/Netskope) is re-signing traffic with a root CA that `certifi`
does not carry. Point the framework at a bundle that includes it:

```bash
security find-certificate -a -p /Library/Keychains/System.keychain > ~/mac-ca-bundle.pem
security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain >> ~/mac-ca-bundle.pem
export ACTF_CA_BUNDLE=~/mac-ca-bundle.pem
```

`ACTF_CA_BUNDLE`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE` and `CURL_CA_BUNDLE`
are all honoured, in that order. Note a Zscaler-only `.pem` is *not* enough:
it lacks the public roots, so hosts the proxy does not intercept will fail.

## Environments

`env/qa.yml`:

```yaml
baseUrl: https://qa.example.com
timeout: 30s
verifyTls: true
headers:
  Accept: application/json
```

Add `env/preprod.yml` etc. as needed. Secrets belong in env vars, never here.

---

## Layout

```
src/actf/
  model.py       typed suite model + duration parsing
  yamlio.py      YAML -> model, with up-front validation
  ctx.py         ${...} resolution, type-preserving
  evaluators.py  env / uuid / now / randomInt / file
  matchers.py    14 built-ins + registry
  extractors.py  jsonpath / header / status / body + registry
  auth.py        bearer / password / none
  transport.py   Transport protocol + LiveHttpTransport (httpx)
  engine.py      execute -> assert -> capture -> retry -> cleanup
  report.py      Allure integration + secret masking
  runner.py      pytest glue, suite discovery, tag filtering
suites/          <- interns add files here
env/             per-environment config
tests/unit/      framework's own tests (mock-based, no live env)
```

## Design notes

- **Fail fast on typos.** `expects:` instead of `expect:` is rejected at load
  time rather than silently skipping every assertion in the step.
- **Chain stops at the first failure** — later steps depend on earlier captures,
  so continuing would produce noise, not information.
- **A capture that finds nothing fails its step**, rather than surfacing later as
  a confusing "unknown variable" error.
- **Cleanup never fails a green suite** — a teardown 404 usually just means the
  resource was never created.
- **Transport is a protocol**, so an in-process/ASGI transport can be added
  without touching the engine or any YAML.

## Not built yet

- Google SSO via Playwright (`auth: {type: google}`) — deferred; there is no
  `id_token` exchange endpoint on the backend, so it needs a real browser leg.
- In-process transport (needs a Python-side app or ASGI target).
- Parallel step execution, response schema validation, data-driven suites.
