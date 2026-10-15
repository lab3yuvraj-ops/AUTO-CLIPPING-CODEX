# Fresh Gemini3.8 benchmark: Le-aS0FTv3s

16October2026, performance-optimization. Source https://youtu.be/Le-aS0FTv3s,
1091seconds (18m11s),1080p30. One requested Reel. No main changes/publication.

## Outcome

**Incomplete: no MP4 preview exists.** Gemini generation access worked on the
second attempt (HTTP200), but its response failed the existing finish/JSON/
grounding/schema validation. No semantic-proposed-spec.json was accepted. The
quality guard was preserved; no rendering or crop approval occurred.

The integration retained token usage/status but discarded the invalid response
and precise validation exception. Therefore the exact defect cannot be
reconstructed; do not claim a particular box/field caused it or a semantic pass.

First request: HTTP503,6.505635500s latency. Built-in2s backoff attempted quota
admission, but1RPM blocked an immediate second generation request. One bounded
retry was invoked after the rolling window cleared, same model/limits. It
returned200 after88.531870200s. No third request or model/provider substitution.
Billing-disabled/unlinked verification passed before execution and again before
every inference attempt. No billing/IAM/API-service changes or paid service.

## Measured timing and usage

- Analyze CLI start to final semantic CLI end: **420.504644632s**
  (7m00.504644632s). Time to failure, not a finished Reel.
- Interactive phase union: **128.028090477s**.
- Between-command union:255.127648354s, including interactive work/quota wait
  and overlapping background work. Never add it to total.
- Residual unattributed gaps:42.591847420s. Not backfilled as invented review,
  inference or idle time.
- API latency sum95.037505700s;2 generation attempts;9 immediate management
  requests across semantic invocations, plus3 successful pre-run management GETs.
- HTTP200 usage: prompt94,561; output2,875; thoughts5,310; total102,746.
  HTTP503 provided no usage. Complete aggregate usage is therefore unknown.
- Estimated incremental Gemini cost$0 under the verified unlinked Free project;
  no invoice measurement. Codex usage, bandwidth/electricity excluded.
- Full renders0, render corrections0, pre-render/final inspection passes0.

Browser setup happened earlier and is excluded. Literal URL-receipt time was not
instrumented. Successful read-only verification before analyze is separate setup;
the matching media scope begins at analyze. Reporting afterward is excluded.

| Stage | Seconds |
| --- | ---: |
| Metadata |6.170068026|
| Caption draft |2.758775473|
| Proxy transfer |11.084613562|
| Full-quality transfer |16.821378469|
| Eligibility envelope including proxy wait |12.242216587|
| Proxy wait within eligibility |11.075959206|
| Chronological overview |0.901981115|
| Selected details CLI, tentative range |1.913888454|
| Selected details CLI, tighter range |1.778211594|
| Gate CLI |0.121084213|
| Selected verification envelope |20.438707829|
| Selected-word inference within verification |10.314190388|
| Dense proxy extraction during verification |1.789162636|
| Start/end audio anchors |0.381947756|
| Full-quality wait after selection |0.005025387|
| Selection reading |38.007451057|
| Scene planning, first session |38.225009441|
| Scene planning, revised selection |24.641157627|
| Spec/word reading and writing |26.001011848|
| Later speech repair writing |1.153460503|
| First semantic stage including management/backoff |19.280867815|
| Second semantic stage including management |93.988402843|
| First failed recheck CLI |0.011785984|
| Successful recheck CLI |4.843930006|

Nested/overlapping stages must not be summed. Full transfer overlapped proxy/
draft; selected verification overlapped dense extraction. timing-report.json
retains complete precision, all CLI envelopes, overlaps and residual gaps.

## Freshness and editorial quality

Fresh footage, captions, selection, ASR, frames, anchors and model requests for
this source. Installed CPU/int8 Whisper, font and approved CTA are reused setup
assets. Full-quality reuse after selection is the accepted same-run transfer,
not historical footage. No Gemini cache hit or old approval reused.

Read the entire native automatic English draft and viewed4 chronological sheets.
Inspected8 selected sheets for tentative967.4–1024.8; refined ending to the
complete reveal and inspected all6 current selected sheets. Both extraction
costs remain included. Verified provisional story967.5–1015.95 (48.45s),174
local word entries. Gemini received72 adaptive frames. No proxy was rendered.

Both proxy/final anchors passed with zero measured offset/drift. No diarization:
performed offscreen narration cannot map audio identities to animated characters.
Hands freezing/pulling away and character reactions matter to this story; no
face-only identity guess was approved. Some broad hair/head close-ups need
genuine full-subject crop review. No narrow-box/border/zoom workaround was used.

No accepted plan/final MP4 exists, so semantic framing, caption animation and
final audio-sync quality cannot be certified. Original style/audio/CTA/encoding
were not changed. Local small/beam5 words were verified; low-confidence 'and'
at992.40 was rechecked at992.62–992.70 with0.974 confidence and repaired with
original evidence retained. 'She' near981.92 remained0.24 in the initial and
independent short recheck; careful-mode wording review remains unresolved.
No fast skip-once rule was applied or invented approval recorded.

First recheck failed because careful section children lack local-audio.wav.
Final-source mono16k audio was explicitly extracted, then recheck succeeded.
That recovery cost remains included; this is a remaining implementation defect.

## Comparison and bottlenecks

Historical964.540154696s (16m04.54s) completed a different34.4s story from16m37s
source and disclosed residual quality limits. This18m11s source/48.45s candidate
with real Gemini stopped at a quality guard. **Seven minutes to failure is not
a speedup against a finished Reel.** No valid completed-output comparison.

1. Preserve private invalid proposals and sanitized exact finish/parse/schema/
   grounding exception paths, with tests. Diagnose locally without another
   inference; never silently accept invalid output.
2.72 frames used94,561 prompt tokens and88.53s API latency. Benchmark adaptive
   scene representatives preserving every required cut/motion witness; compare
   quality/tokens rather than silently dropping evidence to meet a time target.
3.128.03s operator phases, quota-admission wait and42.59s unattributed gaps.
   Return actual next-admissible quota time instead of2s retry under1RPM; provide
   final-source audio extraction for careful children as already done for fast
   children. Preserve two-recheck/review caps and all approval safeguards.

Private artifacts: workflow/jobs/Le-aS0FTv3s-sections-0dd9a6b8 and its -clip1
sibling. Saved preparation can resume but must be labeled reused. No completed
preview path is fabricated, and no quality/publication approval is implied.
