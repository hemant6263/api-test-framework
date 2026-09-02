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
| `login` | fully configurable login flow — see below |
| `none` | no auth |

**Why bearer is the default:** an API key bypasses session handling,
CSRF *and* TOTP. Password login returns a session cookie (not a JWT), and if the
tenant enforces TOTP it cannot complete unattended — the framework says so
explicitly rather than looping on 403s.

Auth resolves **once per suite** and is cached, so a login is not repeated per step.

Secrets never go in YAML. Use `${env:...}`, and note that everything attached to
an Allure report is masked (`Authorization`, `Cookie`, `password`, `token`, …).

### `login` — a custom login endpoint

`password` is hardcoded to this API's actual login shape (`POST
/public/login`, `{email, password}`, session cookie + `X-CSRF-TOKEN`
response). `login` is the escape hatch for anything else: the endpoint,
request field names, what to extract from the response, and **where each
extracted value goes on later requests** are all declared in YAML. Nothing
is auto-applied — if a captured value isn't named under `headers:`,
`cookies:`, or `query:`, it's never sent:

```yaml
auth:
  type: login
  loginPath: /auth/token          # required
  loginMethod: POST                # default POST
  usernameField: email             # login request body field names
  passwordField: password
  username: ${env:AC_USER}
  password: ${env:AC_PASS}
  capture:                         # same shape/extractors as a step's capture:
    token:   "$.data.token"                              # jsonpath (default)
    csrf:    { from: header, path: x-csrf-token }
    session: { from: cookie, path: QA_SESSION }           # new: cookie extractor
  headers:
    Authorization: "Bearer ${token}"
    X-CSRF-TOKEN: "${csrf}"
  cookies:
    QA_SESSION: "${session}"
  query: {}                        # same idea, for query-param auth
```

`capture:` reuses the extractor registry — including the new `cookie`
extractor (`{from: cookie, path: <name>}`, pulls one named cookie's value
out of `Set-Cookie`, usable in step `capture:`/`expect:` too, not just
here). `headers:`/`cookies:`/`query:` are plain `${...}` templates resolved
against the captured values, so `${token}` only works if something in
`capture:` actually captured a variable named `token`.

`login` is available to `loadsuites/*.yml` scenarios too — the load runner
resolves auth through the same registry as correctness suites.

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

### Running suites in parallel

Each suite is a separate `pytest.mark.parametrize` case (`test_suite[suite-name]`
in `tests/test_suites.py`), so pytest already treats them as independent test
items — nothing about the runner itself is sequential, it's just that plain
`pytest` executes test items one at a time. Install
[`pytest-xdist`](https://pypi.org/project/pytest-xdist/) (included in the `test`
extra) to fan them out across workers:

```bash
.venv/bin/pip install -e ".[test,allure]"   # pulls in pytest-xdist

pytest tests/test_suites.py -n auto -m live      # one worker per CPU core
pytest tests/test_suites.py -n 8 -m live         # or a fixed worker count
```

Safe by default: every bundled suite names its own resources with `${uuid}`
and cleans up after itself, so suites never collide when run concurrently.
Each xdist worker is a separate process, so the `session`-scoped `SuiteSession`
fixture is per-worker, not shared across workers.

If you add a suite that touches a **fixed, shared resource** (a well-known
name, a singleton record, a rate-limited endpoint), either give it a unique
name too, or pull it out of parallel runs with a dedicated tag:

```bash
pytest tests/test_suites.py -m "live and not serial" -n auto   # parallel-safe suites
pytest tests/test_suites.py -m "live and serial" -n 0           # one at a time
```

#### Checklist: is a suite safe to run in parallel?

Before adding a new suite (or moving an existing one out of `serial`), confirm:

- [ ] **Every resource it creates has a unique name** — suffix with `${uuid}`
      (see `productName`, `testEmail` in the existing suites), never a fixed
      literal another run could also use.
- [ ] **Every read/update/delete targets an ID this suite itself captured** —
      via `capture:` from its own `create` step — never a fixed ID, a
      well-known/default record, or a filter broad enough to match another
      suite's or worker's data.
- [ ] **Cleanup deletes by captured ID, not by a filter** — `DELETE
      /resource/${capturedId}`, never "delete anything matching this name/
      email/filter," which could sweep up a concurrently running suite's data.
- [ ] **No dependency on another suite having already run** — no shared
      `vars`, no assumption about ordering or state left behind by a
      different `.yml` file. Suites run in whatever order xdist schedules them.
- [ ] **Doesn't hit a rate-limited or quota'd endpoint** at a volume that only
      breaks under N-way concurrency (not a data collision, but same symptom:
      a flake that only reproduces under `-n`).

If any box can't be checked, tag the suite `serial` and keep it out of `-n
auto` runs (`-m "live and serial" -n 0`) rather than risk an intermittent
failure that's hard to reproduce outside CI.

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

## Load testing

Separate from correctness suites — a load run measures throughput and
latency, it doesn't assert pass/fail per request. Scenarios live in
`loadsuites/*.yml` and run via a standalone CLI, not pytest:

```bash
python -m actf.load run loadsuites/product-list-load.yml
python -m actf.load run loadsuites/product-list-load.yml --env preprod --json results.json
```

```yaml
name: Product list under load
env: qa
auth: { type: bearer }

request:
  method: GET
  path: /api/product

profile:
  vusers: 20        # concurrent virtual users (asyncio tasks, not threads)
  duration: 60s      # or totalRequests: 500 — whichever you set stops the run
  rampUp: 10s        # vusers start staggered over this window, not all at once
  rampDown: 5s        # and taper off the same way at the end
  targetRps: 50       # optional: hold a rate instead of "as fast as possible"

thresholds:
  maxErrorRate: 0.02  # fraction, 0.0-1.0
  maxP95Ms: 800
  maxP99Ms: 1500
  maxStatus: 500       # a response >= this status counts as an error (default 400)
```

While a stage runs, a live status line updates every 2s (requests, RPS,
error%) so a long `duration:` run isn't silent — `--progress-interval 0`
disables it. It's cleared before the final table prints.

Console output is a per-stage table (requests, error%, RPS, p50/p95/p99,
max latency); `--json` writes the same numbers machine-readable. The process
exits non-zero if any stage breached its thresholds.

### Finding the breaking point — sweeps

For "how big can the payload get before this breaks" style testing, add a
`sweep:`. Each stage runs the full load `profile:` against a variant of the
request; the sweep **stops at the first stage that breaches `thresholds:`**
rather than continuing to hammer an already-degraded endpoint — the finding
*is* which stage broke.

Two stage shapes, pick whichever fits the mutation:

```yaml
# Scalar sweep: same request, one number grows each stage.
sweep:
  - label: "descriptionLen"
    vars:
      description: { range: [1000, 50000, 5000] }   # 1000, 6000, 11000, ... chars

# Explicit stages: for structural changes a generator can't express
# (drop a field, change a type, add nesting) — list each one out.
sweep:
  - label: "missing name field"
    request: { method: POST, path: /api/product, body: { description: "x" } }
  - label: "name as a number instead of a string"
    request: { method: POST, path: /api/product, body: { name: 12345 } }
```

`vars:` values are available in the request via `${name}` the same way suite
`vars:` are; an explicit `request:` on a stage overrides the scenario's
`request:` entirely for that stage. See
`loadsuites/product-create-payload-sweep.yml` for a full example of both.

### Multi-step flows (`flow:`) — experimental

**Experimental — a few gaps are still open, listed below.** A load scenario
can drive an ordered journey per vuser (login → create → read) instead of a
single endpoint. Use `flow:` in place of `request:` (exactly one of the two
is required):

```yaml
name: checkout journey
env: qa
auth: { type: none }          # flow steps handle their own auth, see below

flow:
  - name: login
    request: { method: POST, path: /login, body: { user: "${user}" } }
    capture: { token: "$.token" }
  - name: create
    request:
      method: POST
      path: /items
      headers: { Authorization: "Bearer ${token}" }
      body: { name: "x" }
    capture: { itemId: "$.id" }
  - name: read
    request: { method: GET, path: "/items/${itemId}" }

profile:
  vusers: 10
  totalRequests: 300    # counts individual requests, not journeys — 100 iterations here
```

Each vuser iteration walks the flow in order; `capture:` on a step (same
shape as a correctness suite's `capture:`) feeds `${name}` into every later
step in that same iteration, via a fresh `SuiteContext` per iteration. The
report gets **one row per flow step**, labeled `scenario/stepName`, so you
can see exactly which step in the journey is slow or breaking rather than
one blended number for the whole flow.

A few things work differently from a single-`request:` scenario, by design:

- **`targetRps`/`vusers` pace whole iterations** (one journey per tick);
  **`totalRequests` counts individual HTTP requests** across all steps, not
  journeys — matching what a real client would call "requests sent." A
  3-step flow with `totalRequests: 300` runs 100 iterations.
- **No per-step auth.** A flow step is just a request — there's no
  auth-state machinery threading a login through the rest of the iteration
  automatically. Use `auth: {type: none}` and thread a captured token into
  later steps' `headers:` yourself, as in the example above.
- **A failing step doesn't abort the iteration.** If `login` errors (bad
  status, or a capture that can't resolve), `create` and `read` still run
  that iteration with whatever's available — a missing `${token}` just
  fails whichever step actually needs it, recorded as an error for that
  step alone. This means every step gets full load even when an earlier one
  is flaky, at the cost of downstream steps failing on missing captures
  until the upstream issue is fixed.
- **Thresholds apply uniformly to every step's summary.** There's no
  per-step override yet, so a `thresholds:` block tuned for a fast cached
  read may be too strict for a slower login step. Any step breaching stops
  processing (there's no sweep support for flows yet, so this only matters
  for the exit-code/`breach_reason` on that step's row).
- **No sweep, no live progress, no `--csv-samples`, no `expect:` per step**
  yet for flow scenarios — see the "Not built yet" list.

### Warm-up period

Connection-pool cold start (DNS, TLS handshake, first request) can skew
p50/p95/p99 on short or moderate stages. Discard the early samples from the
stats without discarding the requests themselves:

```yaml
profile:
  vusers: 20
  duration: 60s
  warmUp:
    seconds: 5      # discard samples taken in the first 5s of the stage
    requests: 50     # AND/OR discard the first 50 samples (across all vusers)
```

Either knob (or both) can be set — a sample is warm-up if *either* condition
still holds. Warm-up requests are still sent and still counted in the total
requests dispatched (so `route.call_count`-style assertions and error
budgets aren't silently different), just excluded from `requests`,
`error_rate`, and the percentiles in the summary; the discarded count shows
up separately as `warm_up_requests` in the console note and the JSON output.

### Response body assertions (`expect:`)

A status code alone can't catch "200 OK but the body says FAILED." Add an
`expect:` list — reuses the same extractors/matchers as correctness suites
(see the built-in matcher table above):

```yaml
expect:
  - { path: "$.status", neq: "FAILED" }
  - { path: "$.items", notEmpty: true }
```

Any assertion failure counts the response as an error (it can trip
`thresholds.maxErrorRate`) even on a 2xx status — `maxStatus` still owns
status-code classification, `expect:` is for the body. A sweep `stage:` can
override the scenario's `expect:` with its own list; omit it on a stage to
inherit the scenario's.

Only `path`/`jsonpath`/`jsonpath2`/`header`/`status`/`body` extractors and
the built-in matchers are supported here — no `fn:`/inline-expression
assertions, since those need `functions:` YAML wiring that load scenarios
don't have.

### CSV output

```bash
python -m actf.load run loadsuites/product-list-load.yml \
  --csv summary.csv --csv-samples requests.csv
```

`--csv` is `--json`'s numbers in spreadsheet form — one row per stage
summary. `--csv-samples` is the one for feeding a time-series dashboard
(Grafana etc.): one row per request (`stage,seq,elapsed_s,latency_ms,status,
error,warm_up`), written incrementally as the run progresses and buffered
(flushed every 500 rows) so it doesn't hit disk on every single request.

### Distributed load generation (`--workers`)

One asyncio event loop caps throughput to what a single process can push.
`--workers N` fans `vusers`/`totalRequests`/`targetRps` out evenly across N
OS processes on this machine, each running its own event loop, and merges
their results back into exactly one summary row per stage — same report,
same threshold/sweep-breach behavior, just more concurrent throughput:

```bash
python -m actf.load run loadsuites/product-list-load.yml --workers 4
```

Single machine only — this is not a distributed-across-hosts load
generator. `--workers > 1` also can't be combined with `--progress-interval`
or `--csv-samples`: a live-progress/CSV callback can't safely cross a
process boundary, so the CLI rejects that combination up front rather than
silently dropping progress. Pass `--progress-interval 0` alongside
`--workers` to run without live output.

### HTML report

```bash
python -m actf.load run loadsuites/product-list-load.yml --html report.html
```

A single self-contained HTML file — no external JS/CSS, safe to email or
drop in a shared folder — with per-stage bar charts (RPS, p95/p99 latency,
error rate) plus the same numbers as the console table, breached stages
highlighted. Stage-level only, even alongside `--csv-samples`: charting tens
of thousands of per-request points would either bloat the single-file
promise or need a JS runtime. Per-request time series is what `--csv-samples`
is for; this report answers "which stage broke."

### Design notes specific to load

- **Async, not threads.** `AsyncHttpTransport` (httpx.AsyncClient) drives all
  vusers from one event loop — cheap enough to run thousands concurrently,
  unlike a thread per vuser.
- **Auth resolves once, synchronously**, before load starts — same as the
  correctness engine, and for the same reason: a single blocking login call
  up front is a non-issue, and it keeps `AuthProvider` implementations sync.
- **A sweep is a safety feature, not just a convenience.** Stopping at the
  first breach means you don't spend the rest of the run hammering an
  endpoint that's already falling over.

---

## Layout

```
src/actf/
  model.py       typed suite model + duration parsing
  yamlio.py      YAML -> model, with up-front validation
  ctx.py         ${...} resolution, type-preserving
  evaluators.py  env / uuid / now / randomInt / file
  matchers.py    14 built-ins + registry
  extractors.py  jsonpath / header / status / body / cookie + registry
  auth.py        bearer / password / login / none
  transport.py   Transport protocol + LiveHttpTransport (httpx) + AsyncHttpTransport
  engine.py      execute -> assert -> capture -> retry -> cleanup
  report.py      Allure integration + secret masking
  runner.py      pytest glue, suite discovery, tag filtering
  load/          load testing: model, loadio (YAML parsing), async runner,
                 metrics (percentiles), report, html_report (SVG charts,
                 no JS deps), __main__ (CLI)
suites/          <- interns add correctness tests here
loadsuites/      <- load/stress scenarios go here
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
- Parallel step execution *within a correctness suite*, response schema
  validation, data-driven suites. (Load scenarios — a different YAML shape —
  do run concurrently; see **Load testing** above.)
- Multi-machine distributed load (`--workers` fans out across processes on
  one machine only, not across hosts).
- Flow scenarios still have open gaps — see **Multi-step flows** below:
  per-step thresholds, sweeps over a flow, and live progress/CSV-sample
  streaming (`on_progress` gets a `dict[str, StageMetrics]` for a flow, not
  a single `StageMetrics`, so `LiveProgressPrinter`/`CsvSampleWriter` from
  the sections above don't work against a flow scenario yet).
