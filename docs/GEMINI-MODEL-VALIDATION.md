# Selected Gemini model: 3.8 Flash

Checked16October2026 IST (15OctoberUTC), on `performance-optimization` only.
This update authorizes configuration/read-only discovery and local mocked tests,
**not generation or a video benchmark**.

## Evidence and limitations

- Official authenticated `GET https://generativelanguage.googleapis.com/v1beta/models`
  returned63 model records in one page for the configured key. The exact entry
  `models/gemini-3.8-flash` advertises `generateContent`,1,048,576 input tokens
  and65,536 output tokens. Full private receipt: `workflow/gemini-model-discovery.json`.
  Use `reel.py gemini-models` to repeat paginated read-only discovery. It never
  selects a model, generates content or treats every listed model as free.
- Google's [model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
  confirms image/text inputs, text output and structured outputs.
- Google's [standard-tier pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.8-flash)
  lists free input/output for the Free tier. This integration uses ordinary
  generateContent only, without tools, paid caching, Batch, Flex or Priority.
- The signed-in project's [AI Studio quota page](https://aistudio.google.com/rate-limit)
  showed **Free tier**, and the3.8 Flash Text-out row showed active caps:
  **5 requests/minute,250,000 input tokens/minute,20 requests/day**, with displayed
  peak usage0 in each row. These are observed limits, not a permanent guarantee;
  usage reporting can lag. Local budgets remain more conservative at
  **1RPM,150,000TPM,20RPD**, shared by project across keys and configured models.
- Authenticated read-only key-owner, active matching project and unlinked-billing
  checks passed again after selecting3.8. Project ID/receipt are private local
  configuration. Every authorized inference repeats these checks. No billing,
  IAM or API service was enabled.

ListModels is capability discovery, not proof that generation will succeed.
The previous2.5 failure demonstrated that distinction. **No3.8 generation
request has been made**, so actual model access, semantic accuracy, latency,
token usage and end-to-end improvement remain unmeasured. The first authorized
request can still fail; existing fail-closed behavior remains.

## Implementation

The default and this machine's deliberately selected `GEMINI_MODEL` are now
`gemini-3.8-flash`, selected only after the evidence above. Explicit legacy
`gemini-2.5-flash` remains available to eligible existing users, retaining its
old settings. Profiles are not a fallback list. No alias or discovered model
is automatically selected. Other models need separate review and approval.

For3.8, the [official generateContent migration guide](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.8)
replaces thinkingBudget with thinkingLevel. This implementation uses **medium**,
the documented quality default, and removes deprecated temperature/topP/topK
settings. It retains JSON MIME mode, local grounding/schema validation and the
existing8,192 output-token cap. Minimal thinking is unsupported; it is not sent.
The legacy2.5 profile retains temperature0/thinkingBudget0 only when explicitly
configured. Model, complete generation profile, prompt revision, implementation,
source, frames, transcript and base spec bind each cache entry. Cross-model
responses cannot satisfy the current model's grounding check or authorization.

Only `gemini_free.py`, configuration/discovery CLI, tests and documentation are
changed. Whisper, OpenCV, full-height camera, caption typography/animation,
audio, CTA, render settings, review/identity safeguards and publication approval
are preserved. Proposals remain unresolved/unconfirmed until genuine review.
No new dependency or paid service is introduced.

## Exact benchmark commands — run only after new authorization

For this machine's existing checkout:

```powershell
Set-Location 'C:\Users\sharm\Downloads\GAGAN EDIT AUTOMATION\workflow\public-clone-smoke-20261015'
$py = 'C:\Users\sharm\Downloads\GAGAN EDIT AUTOMATION\.venv\Scripts\python.exe'
$env:GEMINI_MODEL = 'gemini-3.8-flash'
$env:LOCAL_MODEL_DIR = 'C:\Users\sharm\Downloads\GAGAN EDIT AUTOMATION\data\models'
$env:LOCAL_DEVICE = 'cpu'
$env:LOCAL_COMPUTE_TYPE = 'int8'
$env:SSL_CERT_FILE = 'C:\Users\sharm\Downloads\GAGAN EDIT AUTOMATION\.venv\ca.pem'
$env:PROCESSING_MODE = 'smart'
& $py reel.py doctor
& $py reel.py gemini-verify --confirm-free-tier
& $py reel.py analyze --url 'https://youtu.be/3uYendU1XMk' --clips 1 --fresh --fresh-captions
```

Retain existing private authorized YouTube cookie configuration. Enter any
missing/expired credentials through the private environment setup in
[GEMINI-FREE-TIER.md](GEMINI-FREE-TIER.md), never literal shell arguments/chat.
If verification fails, stop before inference. The analyze command starts fresh
preparation; it does not silently run Gemini or approve an edit. Continue the
documented selection/word/anchor preparation and required phase marks, using
the **new** job IDs and source-bound files. The exact authorized model stage is:

```powershell
& $py reel.py semantic-plan $clipJob --base $base --details $details --authorize-gemini
```

`$clipJob`, `$base` and `$details` must come from that fresh run, not the old
blocked benchmark. See the setup guide for these variables and all subsequent
plan-check/review/render/final-inspection/timing-report commands. This is the
existing operator-assisted workflow, not a new unattended one-command editor.
No Instagram command is part of this benchmark. Compare completion against
964.5401546955109s only after a genuinely successful matching-scope fresh run.

## Local validation

Tests prohibit real HTTP in the Gemini fixtures and use mocked responses.
They cover3.8 request settings, preserved legacy settings, model/profile cache
isolation, unknown-model rejection, bounded read-only pagination, malformed/error
responses, redaction, unchanged billing/quota/retry guards and unapproved-plan
render blocking. Validation: **302 local tests passed in67.97s**, including46 focused Gemini tests (2.57s). This update
makes zero generation requests and does not render or publish any video.
