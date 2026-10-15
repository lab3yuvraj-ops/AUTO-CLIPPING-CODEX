# Gemini free-project visual analysis

Implemented on `performance-optimization`. No main merge or Instagram publication.
Only Google's Gemini Developer API is allowed for semantic vision. The previous
generic chat-completion endpoint is rejected, including localhost VLM endpoints.
Local OpenCV tracking and local Whisper remain available; they are not hosted AI
services. No new Python dependency, CUDA package or paid service is required.

## Model and free-project verification

Official pricing was checked on 16 October 2026 IST (15 October UTC):
[standard gemini-3.8-flash](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.8-flash)
lists free input/output for the free standard tier. Read-only ListModels and project quota review selected this exact model; see [the validation record](GEMINI-MODEL-VALIDATION.md). This does NOT make the model free on
a paid project. Image-generation variants, Pro, arbitrary Flash aliases, Vertex,
Batch, Flex, search/maps grounding and server-side paid caching are not used.
The selected exact profile is `gemini-3.8-flash`; explicit legacy `gemini-2.5-flash` remains for eligible existing projects. These two entries are NOT a fallback sequence. Unknown aliases/models fail closed.
The pricing allowlist expires after30days and requires a new official-doc review.

A `GEMINI_API_KEY` does not expose a trustworthy free/paid-plan flag. Before each
inference attempt, this implementation requires BOTH:

1. You confirm the exact key/project shows **Free** in
   [AI Studio API keys](https://aistudio.google.com/api-keys), supports this model
   in your region, and has active free limits. Set local admission limits no
   higher than those shown in [AI Studio rate limits](https://aistudio.google.com/usage?tab=rate-limit).
2. Read-only Google management checks establish the key owner, resolve its active
   project ID, and verify `billingEnabled=false` with no linked billing account.
   This rejects even a linked inactive billing account.

The second check uses a separate short-lived Google OAuth access token with
permissions for `apikeys.keys.lookup`, `resourcemanager.projects.get` and billing
information reads. Project Viewer plus API Keys Viewer may be appropriate; use
least privilege. The account must be permitted to read the project. The app does
not grant roles, enable APIs, link/unlink billing or purchase anything. If Google
returns403, fields are missing, the token expires, key/project mismatch occurs,
or any check is unavailable, inference stops. A local confirmation flag alone
cannot bypass the management checks. The current project passed these read-only checks for the previous2.5 attempt; every new inference still repeats them.

Google does not provide an atomic “free-only” generateContent switch. These are
immediate read-only billing snapshots, not a platform-level spending guarantee
against somebody linking billing between check and inference. Use a dedicated
project that stays unlinked; do not grant other automation billing-management
permissions. If this administrative guarantee is insufficient, leave Gemini off.

Official references:

- [Billing and usage tiers](https://ai.google.dev/gemini-api/docs/billing)
- [Project-level rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [API key owner lookup](https://docs.cloud.google.com/api-keys/docs/reference/rest/v2/keys/lookupKey)
- [Project lookup](https://docs.cloud.google.com/resource-manager/reference/rest/v3/projects/get)
- [Read project billing](https://docs.cloud.google.com/billing/docs/reference/rest/v1/projects/getBillingInfo)
- [Image inputs](https://ai.google.dev/gemini-api/docs/image-understanding)
- [JSON outputs](https://ai.google.dev/gemini-api/docs/structured-output)

Free-tier content may be used by Google to improve its products under the
applicable terms; do not send footage/transcripts you cannot share with Google.
No video upload or Files API is used: bounded, resized JPEGs and selected
transcript text go to the official HTTPS generateContent endpoint.

## Setup commands — run locally, never paste keys into chat

In the repository root, ordinary student installations use:

```powershell
git switch performance-optimization
$py = '.\.venv\Scripts\python.exe'
& $py reel.py doctor

# A hidden prompt keeps the literal key out of PowerShell history/arguments.
$secureGeminiKey = Read-Host 'Gemini API key from your Free project' -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new('', $secureGeminiKey).Password
Remove-Variable secureGeminiKey
$env:GEMINI_MODEL = 'gemini-3.8-flash'
$env:GEMINI_PROJECT_ID = Read-Host 'Exact project ID shown for that key in AI Studio'
$env:GEMINI_ENABLED = 'true'

# Only after checking AI Studio Free plan, regional access and active quotas:
$env:GEMINI_FREE_TIER_CONFIRMED = 'true'
$env:GEMINI_RPM = Read-Host 'Local RPM budget, no higher than your active free RPM (suggest1)'
$env:GEMINI_RPD = Read-Host 'Local RPD budget, no higher than your active free RPD (suggest20)'
$env:GEMINI_TPM = Read-Host 'Local TPM budget, no higher than your active free TPM'

# Optional Google Cloud CLI is only for obtaining a short-lived management token.
# This does not configure billing. Do not run any billing-enable command.
gcloud auth login
$env:GOOGLE_OAUTH_ACCESS_TOKEN = (gcloud auth print-access-token).Trim()
& $py reel.py gemini-verify --confirm-free-tier
```

If Google Cloud CLI is unavailable, obtain an appropriately scoped short-lived
OAuth access token through your own approved Google login flow and enter it via
the same hidden prompt pattern into `GOOGLE_OAUTH_ACCESS_TOKEN`. A service-account
key file is not required. Expired OAuth tokens must be refreshed explicitly.
The app never prints tokens. Google's lookupKey endpoint requires the key in
its HTTPS query; do not enable raw HTTP debug/proxy request logging.

An ignored local `.env` supports the same variables. `.env.example` contains only
empty examples. Do not commit credentials or use key literals in CLI arguments.
Credentials stay in the local ignored environment. Never include them in student exports or tracked files.

For this machine's isolated checkout only, use the existing production Python
environment without copying its `.env`:

```powershell
Set-Location 'C:\Users\sharm\Downloads\GAGAN EDIT AUTOMATION\workflow\public-clone-smoke-20261015'
$py = 'C:\Users\sharm\Downloads\GAGAN EDIT AUTOMATION\.venv\Scripts\python.exe'
$env:LOCAL_MODEL_DIR = 'C:\Users\sharm\Downloads\GAGAN EDIT AUTOMATION\data\models'
$env:LOCAL_DEVICE = 'cpu'
$env:LOCAL_COMPUTE_TYPE = 'int8'
```

Use your existing authorized YouTube cookie configuration privately when needed.
Do not copy private credentials into the repository/student export.

## Processing architecture

Native captions, otherwise local base/tiny draft -> complete story selection ->
selected Whisper small/beam5 verification and final/proxy anchors -> adaptive
proxy frames + relevant selected transcript -> Gemini JSON proposal -> existing
SceneTable validation -> review -> OpenCV tracking/eased camera -> FFmpeg ->
technical checks and final inspection -> exact-preview approval (no publication
in benchmarks).

`semantic-plan` crops the transcript/frame input to the chosen30–60second story.
Images are hash-checked and resized to640x480 maximum. The configurable80-frame
ceiling is a safety bound, not a fixed sampling rate. If adaptive cut/motion
witnesses exceed it, the call stops rather than silently dropping coverage. The
response uses JSON mode, then local schema/grounding validation checks continuous
source timestamps, actual evidence-frame hashes, nearby anchors, complete subject
bounds, confidence, and supported scene types. Subjects may be objects, actions,
text, reactions or characters. No face detector/keyword coordinate guess is used.

`semantic-proposed-spec.json` always has `confirmed=false`, `unresolved=true` and
`semantic_review_required=true`. Model confidence is not independent inspection.
It does not rewrite verified words, caption styles, CTA, audio or rendering
settings. Existing OpenCV tracking,1.2s easing/cut resets and full-height
horizontal-only rendering remain. Wide/impossible crops get boundary warnings;
existing quarter-second/eased-camera preflight remains authoritative. No automatic
bordered layout, zoom-out, face-only fallback or unsafe source-box shrink.

This automates initial semantic proposals; it does NOT remove required animated
identity/full-first-pass sheets, baseline inspection, correction cap, final MP4
inspection or approval. An unavailable model, uncertain identity or invalid plan
returns `needs_review`; local/operator processing remains possible, without a
semantic-quality pass. Do not copy an unapproved proposal into the active spec
without required evidence/review.

## Cache, quota and failures

Responses are cached locally with content hashes and signatures over source,
frame hashes/pixels, transcript, base spec, prompt/implementation version, exact
model, output-token setting and project. A verified hit makes zero model calls;
changed relevant inputs invalidate it. Cached proposals never carry approvals.
Changing Gemini code invalidates existing render/review evidence under the
project's existing engine-version rules.

The local locked quota ledger is shared by project across keys/jobs. RPM/TPM
use rolling60seconds; RPD uses conservative rolling24hours. Input/output admission
tokens are conservatively estimated, not billed-token measurements. Keep budgets
at or below actual AI Studio free quotas; other apps' usage can still cause429.

-429: stop immediately, persist Retry-After/cooldown (minimum60s), no same-run
retry, continue local/operator processing or wait for another authorized run.
-500/502/503/504: at most2retries, exponential2/4s or longer Retry-After,
maximum30s total wait by default. Reverify free billing and reserve quota before
each attempt; local quota may stop a retry earlier. Long waits pause instead.
-Connection errors: no retry when acceptance is unknown, to avoid duplicate calls.
-403/404, blocked/truncated/malformed output, unknown model, stale price review:
stop; never substitute another model/provider/tier. No paid fallback exists.

Only sanitized status codes/categories and timings are logged; no provider bodies,
keys, OAuth tokens or prompt/image payloads enter attempt logs. Validated proposals
and token counts stay in the ignored private job folder. Do not enable raw HTTP
debug logging when handling keys.

## Local mocked tests (no real requests)

```powershell
& $py -m pytest tests/test_gemini_free.py tests/test_semantic_analysis.py tests/test_performance_doctor.py -q
& $py -m pytest -q
```

Tests cover disabled/no-authorization paths, free-project verification, key-only
failure, active/linked/mismatched billing rejection, paid-model rejection, stale
pricing, official payload, object prioritization, grounding/schema failures,
unresolved approval state, boundary warnings, hash-cache hits/tampering, changed
inputs, per-project quotas,429pause, Retry-After/backoff, sanitized errors and
existing local caption/camera/render/review regressions. Initial implementation validation:290 local tests passed in84.57s without real network requests. Subsequent2.5 generation was explicitly authorized but stopped on404; see BENCHMARK-GEMINI-3uYendU1XMk.md. Current3.8 validation and test results are recorded in GEMINI-MODEL-VALIDATION.md. No3.8 generation or completed semantic-quality benchmark has run.

## Prepared 3.8 benchmark procedure — AWAITS NEW AUTHORIZATION

Prepared recipe: `benchmarks/gemini-free-3uYendU1XMk.json`. One clip; source16:37;
baseline successful execution964.5401546955109s (16m4.54s), full earlier window
1054.639220714569s including diagnostic/403 recovery. Compare matching scopes.

After you confirm free setup AND explicitly authorize the real test, start fresh:

```powershell
$env:PROCESSING_MODE = 'smart'
& $py reel.py analyze --url 'https://youtu.be/3uYendU1XMk' --clips 1 --fresh --fresh-captions
```

Retain the returned new source job ID. Follow standard complete-transcript/source
selection, `fast-details`, `fast-gate` and `fast-prepare` for careful selected
preparation; do not reuse the old benchmark's selection, words or approvals.
The word `fast` in these shared command names does not opt into fast semantics.
Codex/operator still supplies genuinely reviewed passage evidence/selection and
the base containing verified words. Then use these exact commands with the new
paths printed by preparation:

```powershell
$clipJob = Read-Host 'New clip job ID'
$sourceJob = Read-Host 'New source job ID'
$base = Read-Host 'New base.json path (verified words and selected boundaries)'
$details = Read-Host 'New selected detail.json path'
& $py reel.py phase $clipJob scene_planning --event start
& $py reel.py semantic-plan $clipJob --base $base --details $details --authorize-gemini
& $py reel.py phase $clipJob scene_planning --event end
```

The authorization flag permits only bounded Gemini requests after verification;
it never approves rendering/publication. On blocked/paused/needs_review status,
stop inference and report the cause. If a proposal succeeds, inspect its evidence,
fix only justified targets, and preserve existing pre-render safeguards. After
recording actual reviewed evidence in the final spec:

```powershell
$spec = Read-Host 'Reviewed new spec.json path'
& $py reel.py plan-check $clipJob --edit $spec
& $py reel.py review $clipJob --edit $spec
# Inspect every required first-pass page; mark only pages actually viewed:
& $py reel.py phase $clipJob review_pass --round 1 --event start
# review-inspect accepts repeated --page ABSOLUTE_PAGE after actual inspection.
& $py reel.py phase $clipJob review_pass --round 1 --event end
# Render only when all preflight/review guards pass:
& $py reel.py render $clipJob --edit $spec
# Inspect final opening/ending/CTA/cuts/flags and record actual final pages.
& $py reel.py timing-report $sourceJob
& $py reel.py performance-report $clipJob
```

Keep the existing interactive phase marks around selection, spec writing,
corrections and final inspection. Timing-report reports unions/overlap and
between-command time separately; unexplained gaps must stay unexplained, not
renamed idle/inference. `gemini_semantic_analysis` is an explicit stage;
`semantic-analysis-status.json` and `gemini-attempts.jsonl` record measured total,
API latency, retries/backoff, inference/management counts, cache state and provider
usageMetadata tokens when available. performance-report rolls these up alongside
render/correction counts. Do not add nested or overlapping times.

Report end-to-end scope, time to editing-ready, actual human phases, API calls,
tokens/cost estimate, reused setup assets, defects, two-correction cap, render
count, actual MP4 preview/hash and comparison against964.54s. Target one render;
quality failures still require correction/manual review rather than hiding them.
No performance gain or autonomous semantic-quality pass is established yet.
