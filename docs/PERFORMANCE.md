# Performance optimization branch

This work is isolated on `performance-optimization`. Main and the local production workflow remain unchanged. No publication is authorized.

## Audited baseline

The system is Codex-operated, not a standalone semantic editor: `reel.py` routes commands; `fast.py` prepares careful/fast jobs; native caption caches and selection_draft.py provide draft text; local_transcription.py/speech_worker.py verify selected words; scene_table.py creates grounded specs; preflight.py checks boundaries/crop/motion; review.py and review_policy.py enforce actual pre-render inspection; render.py/fast_render.py encode; final_review.py samples burned output; publishing.py preserves Zernio idempotency and preview approval.

Existing code already overlaps metadata-following full transfers, proxy/draft, selected verification and sections, caches transcripts/word evidence/frames, uses 1.2s eased cameras, renders after review, carries reviewed hashes and caps corrections. It has no autonomous upload notification scheduler or AI clip-selection API. Do not introduce a dashboard or claim these exist.

Saved 15:36 source kWaIeDnLeJ4: 1688.735580s wall, 1045.346884s interactive union, 351.778394s residual unattributed. Saved 16:03 source M6vyYqa0n6g:1691.670536s wall,1030.478472s interactive union,206.636608s unattributed. These are historical measured runs, not a newly executed baseline; overlaps are not additive. The former clip's renderer spent8.292789s on a lossless edit and55.361546s composing/encoding; total64.034263s before validation/CTA. The latter spent9.888796s plus40.279934s,total50.338529s.

## Measured opportunities

1. Direct FFmpeg renderer trims late source passages after decoding the lead-in. Bounded input seeking can remove that redundant decoding without changing crop/ASS/encoder settings.
2. Dense details always use0.5s sampling. Adaptive proxy samples can reduce static duplicates while retaining cuts, motion and transcript transitions; scene identity remains evidence-bound, not keyword-derived.
3. More than half of wall time was interactive story/scene planning and review. Structural plan validation and cached grounded semantic evidence can reduce repeated planning; sampling or face detection alone cannot replace semantic judgment.
4. The careful renderer's lossless/OpenCV scaler and direct FFmpeg scaler are not pixel-identical. Keep backend changes explicit and compare actual pixels/caption events/camera maps before recommending them. Do not change CRF/preset silently.

Fresh end-to-end benchmark awaits the user's new URL. Saved-passage replays must label media, selection, words and model state reused. No3–5-minute or<10-minute claim is established by a component benchmark.

## Saved-passage component benchmarks (this branch)

All footage, passage selection, verified words and reviewed framing were reused. Every output directory was new; encoding/camera/caption events were fresh. These are component replays, not a fresh source-to-clip benchmark. One41.5s clip from the saved15:36 source was used. No posts were made.

| Run | Before direct renderer (no input seek) | Bounded direct renderer | Existing lossless/OpenCV renderer |
|---|---:|---:|---:|
| Sequential pair1 |63.045548s|32.100080s|26.021257s|
| Repeat with optional metrics wrapper |137.114268s|33.188670s|not repeated|

The large baseline variation was observed; the exact cause was not isolated. Do not select the most favorable pair or attribute it to a stage without evidence. The first development baseline65.996156s overlapped a test invocation at its tail and is excluded from the isolated comparison. Both isolated pairs are reported. The existing lossless renderer was fastest here, so it remains the default. `direct` is optional and not a universal recommendation. The changed direct backend saved30.945468s in pair1 (49.0843%), not minutes of end-to-end runtime.

Quality: all1245 decoded video frames of pair1 direct before/after were hash-identical. Fractional/gapped synthetic regressions also protect exact camera/ASS events, all decoded video frames, equal audio sample count, and AAC error below2/32768 peak with >90dB signal/error. Fixture measurement was106.748779dB. Tiny AAC rounding is disclosed; do not claim bit-identical audio. The existing OpenCV and FFmpeg scalers remain different implementations; this comparison does not prove identical pixels between those backends.

CPU/RAM: psutil is absent in this installation, so the optional resource records correctly report unavailable/null. No CPU or peak-RAM numbers were invented. No additional dependency was installed. Local render API calls/cost were0; optional VLM costs are provider-dependent and unknown unless configured/metered. No real VLM calls were made during these tests.

### Adaptive selected-source details

Same saved45s proxy passage, fresh extraction/page generation per mode, no transcript-context anchors in this component replay:

| Profile | Extraction + sheets | Frames for analysis | Generated sheets |
|---|---:|---:|---:|
| Dense baseline |1.280274s|95|8|
| SMART |1.283160s|67|6|
| FAST |1.178177s|41|4|

SMART did not speed extraction in this sample. Less generated material is not measured editorial time saved. No page-count claim replaces actual inspection, and no static/motion quality improvement is asserted from these figures. Actual runtime adds transcript-transition anchors, which can increase counts. Cuts/motion remain mandatory witnesses; the frame budget is soft.

## Run and revert

Use the normal installation; no mandatory dependencies were added. This branch's clean checkout has no creator secrets/model weights/jobs. Configure your own local `.env` and model cache as in ONBOARDING.md.

```powershell
.venv/Scripts/python.exe reel.py doctor
.venv/Scripts/python.exe reel.py analyze --url YOUTUBE_URL --clips 1
# Before rendering a new scene-table spec:
.venv/Scripts/python.exe reel.py plan-check CLIP_JOB --edit spec.json
.venv/Scripts/python.exe reel.py timing-report SOURCE_JOB
.venv/Scripts/python.exe reel.py performance-report CLIP_JOB
```

Settings in private `.env`: `PROCESSING_MODE=smart|fast`, `ADAPTIVE_DETAILS=true|false`, `DOWNLOAD_MODE=auto|selected-sections`, `RENDER_BACKEND=legacy|direct`, `X264_PRESET=fast|veryfast`. Defaults preserve the existing renderer/encoding quality and eager download policy; selected-section mode defers full quality until reviewed selection and retains the existing bounded full fallback. Native captions/proxy overview still precede selection; no draft words are used in final captions. `--fast` caption skip-once handling is separate from sampling profiles.

Optional semantic assistance:

```powershell
.venv/Scripts/python.exe reel.py semantic-plan CLIP_JOB --base base.json --details selected-details.json
```

It uses only an explicitly configured `SEMANTIC_VISION_URL` and `SEMANTIC_VISION_MODEL`; a local CPU vision server must be installed/configured separately. `SEMANTIC_VISION_API_KEY` stays private. Remote HTTPS also requires `SEMANTIC_ALLOW_REMOTE=true`; selected images/transcript leave the machine only with that opt-in. Endpoint/model pricing and CPU latency vary; no price or quality is promised. The response must match SceneTable, bind actual sampled-frame hashes and model version, and pass grounding/geometry checks. An uncertain response saves needs-review status and never invents a box. Output remains an unapproved proposal with `confirmed=false, unresolved=true`, requiring actual inspection before normal render guards allow publication.

For reproducible renderer replay use `tools/benchmark_render.py --source FILE --recipe EDIT.json --output NEW_FOLDER --renderer direct` and repeat with `--no-input-seek`. Never treat benchmark outputs as approved previews; do not reuse historical approval.

Incremental commits separate baseline, bounded seek, adaptive sampling, grounded plan/optional semantic assistance, download policy and distribution. Use `git revert COMMIT` on the performance branch to undo one optimization. Do not merge main without a separately reviewed decision.

## Pending acceptance work

The new source URL is awaited for a fresh full baseline/optimized comparison. Real talking-head, two-person podcast, nature/river-shadow, screen recording and multi-cut footage have not all been tested. Vision protocol tests use mocks and do not demonstrate semantic localization quality. No installed semantic provider is available here, so default operation still needs Codex/operator judgment; unattended student editing acceptance is NOT met. Full first-pass identity and exact-preview publishing guards remain. Do not silently disable them to claim performance.3–5/under10/10–15-minute workflow targets remain unproven.
