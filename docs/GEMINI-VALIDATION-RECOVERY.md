# Gemini validation recovery — 16 October 2026

Branch: performance-optimization. **Zero Gemini generation/management requests**
were made during this diagnostic work. All HTTP tests use fake clients. No
render, publication, main change or merge. Public Google documentation was read.

## Diagnosis

The old HTTP200 response cannot be reconstructed. Saved artifacts retain model,
inputs,88.5318702s latency and94561 prompt/2875 output/5310 thought/102746 total
tokens. Missing: raw response/proposal, response hash, finish reason, complete
JSON status, parse error, exact schema path and grounding exception. Neither
accepted semantic-analysis.json nor semantic-proposed-spec.json exists.

The old request specified JSON MIME type without an actual response schema.
This is a weakness, **not a proven root cause** of that particular rejection.
No specific coordinate/identity error can be inferred from token totals.

The3.8 profile now uses documented generationConfig.responseFormat.text MIME/
schema settings. Explicit legacy2.5 retains responseMimeType/responseJsonSchema,
never as a fallback. Wire schema uses documented constraints; unchanged strict
local validation still enforces exclusive bounds/nonempty strings. Empty scenes
can express refusal on the wire but remain rejected locally. See
[Google structured outputs](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).

## Private diagnostics

Each received response gets ignored job-local private-gemini/TIMESTAMP-ID/
diagnostic.json and response.private.txt. Saved: finish reason, JSON completion/
errors, schema paths/constraints/values, grounding category/path/expected/received,
model/config, response hash/size, signature and source/base/transcript/frame
hashes. HTTP errors are retained privately too. Above2MB, save hash/size metadata
only. Transport failures have no received body. No request headers are saved;
configured key/OAuth literals are redacted even if echoed. Never export private
artifacts to Git/student clones/public issues. Public status exposes category
and private location only, not rejected contents.

Malformed/truncated/duplicate-key/nonfinite JSON, non-STOP finish, schema defects,
source/model mismatch, unknown/out-of-range frames, unwitnessed anchors, missing
independent full bounds, scene gaps and uncertainty remain rejected. Only BOM/
outer whitespace removal is normalized, separately recorded with both hashes.
No coordinate/timestamp coercion, fence stripping, invented identity or box
shrinking. Accepted proposals remain unconfirmed/unresolved. Cache signatures
include model/profile/schema/prompt, validator code, strategy and source evidence.

## Offline frame/token replay

baseline remains default and preserves72 frames. Optional evidence-preserving
removes only redundant static-only samples within4s of a retained sample. Keep
opening/ending, scene cuts, motion witnesses, transcript/context/identity changes,
flags, unknown tags and missing sampling evidence. Log removed hashes/reasons.
This coverage test is not semantic identity approval.

Saved input replay retained all64 mandatory frames and all16 candidate cuts,
removing eight static-only frames: **72→64 (11.1111% fewer)**.

| Strategy | Frames | Local input bound | Including8192 output reserve | Local estimate seconds |
| --- | ---: | ---: | ---: | ---: |
| baseline |72|121631|129823|0.002479700000549201|
| evidence-preserving |64|108831|117023|0.0022016999992047204|

These are conservative local admission estimates,1600/frame plus prompt/schema,
**not provider countTokens or measured savings**. Difference12800 reserved input
tokens (~10.52% of this new baseline). No JPEG/resolution change. Saved comparison:
workflow/jobs/Le-aS0FTv3s-sections-0dd9a6b8-clip1/frame-cost-local-comparison.json.

Old94561/72=1313.3472 tokens/frame includes text and image processing. No modality
breakdown/effective media-resolution record survives; exact image/text attribution
is unrecoverable. JPEG bytes do not directly predict image tokens; see
[Google image documentation](https://ai.google.dev/gemini-api/docs/image-understanding).
New prompt/schema also differ. Actual savings require a future authorized call.

## Other defects

Careful-section rechecks prepare missing/unbound local-audio.wav from accepted
final media as CPU16kHz mono PCM, atomically replaced with source/audio hash
receipt. Reuse requires both hashes. Fast no-recheck and careful recheck caps
remain; this fix grants no extra verification pass.

Quota admission computes the actual next epoch across local rolling RPM/TPM/RPD
and Retry-After. A503 occupies its reservation;1RPM pauses until the real slot
instead of sleeping2s then failing admission. Waits above the configured cap
return paused/next-admissible/retry seconds; oversized token requests have no
slot. Google may impose further restrictions. No paid fallback.

Historical42.59184741973877s is four unchanged command-end→phase-start gaps:

| Gap | Seconds |
| --- | ---: |
| analyze→selection_reading |7.155533790588379|
| details→scene_planning |1.5486721992492676|
| revised details→scene_planning |14.846962928771973|
| prepare→spec_writing |19.04067850112915|

Phase CLI returned before recording command/between-command coverage. Its marker
then became the prior timestamp used by the next command, leaving these earlier
intervals uncovered. This explains the accounting defect, **not actual activity**:
reading/startup/idle cannot be distinguished. No historical phase was invented.
Future phase commands record real coverage under the source timing owner, tested
with a synthetic clock. Overlaps are still not added to total wall time.

## One controlled test — requires new human authorization

Use existing private .env. No key/token arguments. A fresh short-lived management
token may be needed. Existing ownership/project/billing GETs run immediately
before generation; expired verification, linked or enabled billing stops it.
Keep existing certificate configuration and TLS verification.

```powershell
Set-Location 'C:\Users\sharm\Downloads\GAGAN EDIT AUTOMATION\workflow\public-clone-smoke-20261015'
$py = 'C:\Users\sharm\Downloads\GAGAN EDIT AUTOMATION\.venv\Scripts\python.exe'
$env:GEMINI_MODEL = 'gemini-3.8-flash'
$env:GEMINI_RPM = '1'
$env:GEMINI_TPM = '150000'
$env:GEMINI_RPD = '20'
$env:GEMINI_MAX_RETRIES = '0'
$env:GEMINI_FRAME_STRATEGY = 'evidence-preserving'
$clipJob = 'Le-aS0FTv3s-sections-0dd9a6b8-clip1'
$base = "workflow/jobs/$clipJob/base.json"
$details = "workflow/jobs/$clipJob/semantic-input-details.json"

# Offline: no HTTP; safe before authorization.
& $py reel.py semantic-plan $clipJob --base $base --details $details --estimate-only

# STOP here until the human authorizes this one real test.
& $py reel.py semantic-plan $clipJob --base $base --details $details --authorize-gemini
```

At most one generation call/one daily slot out of20,117023 conservative reserved
tokens against150000TPM, plus three read-only management checks when generation
is reached. Matching validated cache sends zero calls and labels reuse. Actual
usage remains unknown until the response; prior HTTP200 total102746. No paid
fallback, model substitution, render or publication in this command.

## Resume plan and tests

Reuse and label saved source/proxy, transcript,48.45s selection, small/beam5 word
evidence, selected frames and passed start/end anchors after hash checks. Do not
run analyze/prepare again. Start at semantic-plan with saved base/details.
Successful proposal still needs careful wording resolution near981.92s within
the existing cap, genuine visual identity/full-bounds review, scene-table build,
preflight/all policy-required first-pass pages, one final render and targeted
final inspection. Code/spec changes invalidate stale review evidence. No
nonexistent approval is reused. Stop on unresolved failure; never publish.
This diagnostic replay cannot establish completed-Reel performance.

Complete local suite: **325 passed in82.64s**. Covers private diagnostics and
redaction, format-only normalization, model-specific schema, mandatory witnesses,
estimates, quota slots, child CPU audio, phase coverage and existing editorial/
render tests. No new dependency or GPU requirement. No generation requests.
