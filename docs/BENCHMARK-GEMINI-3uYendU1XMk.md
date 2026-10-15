# Gemini benchmark stopped at model access

16 October 2026. Branch `performance-optimization`. Source
https://youtu.be/3uYendU1XMk, one requested clip. No main change, publishing,
model substitution or paid-tier change.

## Result

**Not a completed end-to-end benchmark. No MP4 was rendered. No speedup or
semantic-quality improvement has been established against 964.540155 seconds
(16m04.54s).** The exact approved `gemini-2.5-flash` generation request returned
HTTP404, so execution stopped. A separate read-only model metadata request
returned200 and advertised generateContent; model discovery alone therefore
does not prove inference access.

Google's current [deprecations documentation](https://ai.google.dev/gemini-api/docs/deprecations#gemini-25-flash-models)
states that2.5 access is limited to users who actively used those models in the
past. This is consistent with the observed failure, not a proven diagnosis from
the404 body: the integration retained the status but not that provider message.
The model is not documented as shut down. No second inference request was sent
to retrieve a better diagnostic.

## Free-tier verification and credentials

Chrome AI Studio showed Free, with active2.5 Flash limits5RPM,250KTPM,20RPD.
Read-only authenticated API checks verified key ownership, matching active
project, billingEnabled=false and no billing account link. Checks passed again
immediately before inference. No APIs, IAM roles or billing were enabled.
Local admission remained conservatively1RPM,150KTPM,20RPD. Secrets are only in
the ignored local environment; no credential values are included here.

There was one generation attempt, HTTP404, **1.206755200001s** API latency,
three immediate management checks, no inference retry, no cached response.
Provider token usage was absent, not measured zero. Estimated incremental
Gemini charge is$0 on the verified unlinked Free project; no invoice/cost API
measurement was available. Credential setup also made read-only key-management
requests; these are separate from the three per-inference checks. Codex usage,
electricity and bandwidth are outside this incremental Gemini figure.

## Freshness and partial timing

Job `3uYendU1XMk-sections-e0dbc010`, child `...-clip1`. Fresh metadata,
native automatic English caption draft,480p proxy,1080p source, selection,
word verification, anchors and selected frames. Installed CPU/int8 model files,
font and CTA were reused as setup assets. Full-quality reuse after selection
was the accepted download from this same run, not historical cached footage.
No previous editorial decisions or approval were imported.

Measured CLI-start to failed semantic-command end: **184.408796310425s**
(3m04.408796310425s). This is time to failure, not time to a finished Reel.
Browser/credential setup before analyze and diagnosis/code repair afterward are
excluded; literal URL receipt was not instrumented.

| Stage | Seconds |
| --- | ---: |
| Metadata | 6.355554581 |
| Native selection draft | 1.720922709 |
| Full-quality transfer | 15.242550135 |
| Proxy transfer | 15.694600821 |
| Of which proxy wait | 15.683629036 |
| Chronological overview | 0.733638763 |
| Eligibility sample envelope | 16.717118263 |
| interactive_selection_reading_cbf57f11_1 | 35.832336664 |
| Adaptive selected details CLI | 1.135123014 |
| interactive_scene_planning_cbf57f11_1 | 21.734642506 |
| Dense proxy frames during verification | 1.267505884 |
| Of which selected-word inference | 7.350796938 |
| Selected verification envelope | 17.052988529 |
| Proxy/final start/end anchors | 0.352762222 |
| interactive_spec_writing_ec0dae04_1 | 30.461370707 |
| Gemini stage including management/admission | 6.862989664 |
| Interactive phase union | 88.028349876 |
| Residual unattributed gaps | 38.744500160 |

Full renders / corrections / final inspections: **0 / 0 / 0**.

Nested/overlapping values must not be summed. Full transfer overlapped proxy and
draft. Verification overlapped dense extraction. Between-command union was
131.788638830s and included the88.028349876s interactive union. Residual gaps are
unattributed, not invented inference or idle time. See the job's timing-report.json
for full precision and all CLI envelopes.

Fresh transcript/chronological review ranked Nate's refusal to help his violent
brother, with provisional story776.4–809.68. Three overview and five selected
source sheets were actually inspected. No crop/caption review was approved,
no semantic plan was produced, and selected low-confidence speech still needs
normal careful-pipeline resolution. Both audio anchors passed with zero measured
offset/drift. These are preparation results, not a completed quality pass.

## Reporting fix

The first real call exposed a CLI logging bug: semantic statuses such as
needs_review were passed directly to a ledger accepting only success/failed/
rejected, masking the404 with Invalid stage outcome. Provider status now remains
in the diagnostic while the outcome is mapped to the ledger contract. Mocked
tests cover every mapped status plus404 no-retry/no-substitution. The historical
open semantic/workflow intervals were closed at the already recorded failed CLI
end; timing-ledger-repair.json explains this measured-evidence repair. No
historical interactive phase was fabricated.

## Remaining blockers

1. Exact-model generation access: resolve through Google for this project, or
   obtain explicit user authorization for a separately verified supported free
   model before changing the allowlist. Do not switch automatically.
2. Animated semantic identity/framing remains untested with Gemini because no
   proposal was returned. Keep all source review/preflight/final safeguards.
3. Operator planning/review remains the largest measured preparation cost;
   a successful grounded proposal is needed before measuring any reduction.

No completed-output comparison, render speed comparison or visual-quality claim
is possible from this stopped run. Saved fresh preparation can resume, but a
resumed run must label that preparation reused and cannot be called fresh.
