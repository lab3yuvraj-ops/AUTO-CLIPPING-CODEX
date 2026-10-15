# Fresh CPU benchmark: 3uYendU1XMk

Date: 2026-10-16. Source: https://youtu.be/3uYendU1XMk (BlackOut Horror Story), 997 seconds (16:37), 1920x1080/30. Branch performance-optimization; implementation ba43521d6211cc23b46e2793e8e3844413895cbb. No main changes or publication.

## Outcome

A local preview was rendered, technically validated and sampled. This is NOT an unqualified editorial-quality pass or a demonstration of autonomous semantic editing. Two corrections were used; residual issues are retained for human review, with no third correction or publication approval.

- Recorded diagnostic-to-final-inspection wall: **1054.639221 seconds (17m 34.639221s)**. This includes the initial failed fresh download and setup investigation. The literal chat URL-receipt time was not instrumented, so this is the measured execution window, not a claim that pre-tool reading took zero time.
- Successful fresh analyze-to-completion window: **964.540155 seconds (16m 4.540155s)**. Do not substitute this narrower figure for the full execution window.
- Marked operator/Codex interactive phase union: **426.436432s**.
- Between-command union: **699.815728s**, overlapping interactive work; never add it to total. Residual unattributed coverage gaps: **246.108395s**. These are disclosed, not backfilled or called inference/idle. The named speech_recovery envelope also includes concurrent editorial work, not 70.5s of ASR inference.
- 2 full story renders; 2 correction rounds, 3 pre-render review generations, 2 final-MP4 inspections. No infinite loop. Final story 34.400000s; export 38.388s including approved four-second CTA.
- 42 actual sheet views: 3 chronological overview + 7 selected detail + 26 pre-render (12+7+7) + 6 final (3+3). Four additional individual source images viewed. Later pre-render rounds each carried 5 inspected unchanged pages. The first failed final inspection was not recorded as approval; therefore final frame inspection was repeated honestly.

## Installation, freshness and network

Doctor confirmed Windows/Python3.11, available FFmpeg/ffprobe, installed dependencies and CPU operation. Small Whisper CPU/int8, beam5. Cached installed model files, licensed font and existing CTA were reused as setup/style assets; no old video, transcript, selection, analysis or approval was reused. CPU/RAM sampling unavailable because optional psutil is not installed; no invented resource numbers.

Initial isolated-checkout attempt (3uYendU1XMk-sections-c4c1c952) failed media download with HTTP403, because the existing authorized operator-cookie setting was not passed to that checkout. Restoring that private setting through subprocess environment allowed a second completely fresh analyze run; no low-quality file was accepted. No secrets were copied into Git or command arguments. Initial analyze command measured22.209s. Diagnostics/recovery before successful analyze remain in the full execution window.

Fresh native automatic English captions supplied selection-only draft. Local selected Whisper verification established caption IDs/intervals. Proxy/full start-and-end anchors matched within the existing80ms tolerance (verification-route.json). No whole-source local ASR or diarization ran: this animated story has an offscreen narrator, not mappable audio identities. Full1080p transfer took24.957732s and overlapped proxy/captions/overview. The later full_quality_reused_after_selection record means same-run accepted download, not prior-run cached footage. Section downloads were unnecessary for1080p under the configured threshold.

SMART adaptive selected details decoded93 candidates and retained73 analysis frames over44s (cuts/context/motion retained); seven sheets actually inspected. An earlier tentative551–598 details request was replaced with566–610 before verification; both overheads remain logged. Final chosen story566.4–600.8 is complete: robbed woman sees injured boy, bandages him despite her loss. The later question/answer was excluded because its close-up full head could not satisfy portrait safety; no zoom-out or fabricated narrow bounds was used.

## Semantic framing, captions and quality

No real configured vision-language model: doctor semantic_vision_configured=false. Semantic provider calls0, incremental paid API cost$0 (excluding Codex subscription/usage, electricity and bandwidth). YouTube HTTP requests did occur; aggregate request count was not instrumented and is not claimed zero. No Instagram API call.

Codex manually reviewed transcript, source overview, selected source sheets and all required crop/caption pages. Scene-table schema and editing-plan validation bound the actual source hash, complete scene coverage, verified word IDs, style hashes and output contract. Human/operator-authored visual anchors select woman/Caleb heads, then the injured palm and bandaging hands according to story context. The camera remains full-height, horizontal-only with1.2s easing and cut resets. One injured wrist is deliberately shown in the overhead scene; both widely separated wrists cannot fit. No borders, zoom or new layout were introduced.

Existing Creepster, fixed caption position, two-word white/red events, outline/shadow, audio handling and four-second CTA preserved. Audio/video stream duration difference0.001s; verified timing mapping and highlight reset/event checks pass. Encoding1080x1920,30fps,H.264/AAC. Black/freeze/audio checks pass. This verifies stream/timeline consistency, not perfect perceptual lip sync or perfect ASR.

Remaining issues (approval held):
1. Source574.97/output8.567: woman's leaning head is still close to the left crop edge. Automated static safety passed supplied bounds, but sampled pixels reveal the limit of those bounds. Two-correction cap reached; manual decision required. Do not claim every frame is perfectly framed.
2. Source already has burned-in white subtitles. Some remain partially cropped beneath the unchanged custom captions. No inpainting/removal or creative redesign was authorized.
3. Source582.44/output16.04: local ASR twice reads 'gauze'; the draft suggests 'gouges'. The ambiguity is visible in job warnings, not silently repaired. One 'and' interval was corrected from a saved independent high-confidence local recheck, with original evidence preserved in verified-passages.initial.json and caption-timing-repairs.json.

## Render and overlap

Legacy/OpenCV + libx264 fast CRF18 was used because earlier same-machine renderer comparisons favored it over direct FFmpeg; veryfast has not been visually approved. No GPU. First story render35.947206s (lossless edit5.928017, camera0.039010, compose/encode29.929700); second31.123425s (lossless same-run cache0.478389, camera0.048410, compose/encode30.515456). Final sampling4.252s then4.205s; render CLI totals include guards/validation/CTA/sampling. Do not add nested stage times together.

Critical path: source preparation -> operator selection/source review -> selected verification -> plan/preflight/review -> corrections -> final render/inspection. Full transfer overlapped preparation and was ready before selection. Selected verification overlapped proxy dense extraction and accepted-source checks. No API semantic-analysis time was hidden; it was unavailable.

## Historical comparison

Historical user-reported baseline30–35minutes was for roughly15minute sources; it was not rerun on this exact video/branch/hardware state. This source is16:37, one34.4second story plus4second CTA, native automatic draft available, models already installed, manual Codex review,2renders/2corrections, and an initial403 setup recovery. Full measured execution is 41.409% shorter than30minutes and 49.779% shorter than35minutes, but this is a cross-source comparison, not a controlled causal speedup. Under10minutes and10–15minutes were NOT met; editorial acceptance also remains pending.

## Three largest remaining bottlenecks and specific follow-ups

1. Manual semantic planning/review and tool orchestration: 426.436432s marked interaction plus 246.108395s unattributed successful-run gaps. Add a run-scoped prepare/plan/review receipt command and bulk review-inspect for actually viewed pages, automatic job binding for scene-build, and persist request-receipt time. Integrate the existing optional real VLM proposal adapter only when explicitly configured; validate source-bound subject masks/bounds and retain uncertain-scene review. Do not claim manual identity work eliminated today.
2. Inaccurate animated head-motion envelopes cause late corrections: static safety only validates supplied boxes. In scene_table.py/motion_check.py, propagate reviewed full-head bounds over each scene, retain observed extrema/uncertainty, sample actual eased-crop edge witnesses before rendering, and treat edge slack under threshold as a review flag. This addresses this run's missed lean; generic optical flow alone is not semantic identity proof.
3. Repeated preflight/review generation98.514s across3review CLIs plus2renders: key motion/boundary/source-thumbnail caches per scene rather than entire spec, recalculate only changed scenes and caption layers, and scope silence_intervals to selected audio instead of decoding whole video. Preserve every required inspection/hash and cap. No savings from these proposed changes have been measured.

## Complete measured stage ledger

Stages below include wrappers/overlapping work; they are NOT additive. Machine-readable intervals, overlaps, interactive phases and gaps remain in the private job timing-report.json.

| Stage / interval | Seconds | Cached |
|---|---:|---|
| metadata | 8.178675 | False |
| caption_draft | 4.094128 | False |
| proxy_download | 16.067234 | False |
| eligibility_proxy_wait | 16.043836 | False |
| proxy_overview | 0.805501 | False |
| eligibility_sampling | 17.302947 | False |
| cli_analyze | 28.313914 | False |
| full_quality_download | 24.957732 | False |
| interactive_selection_reading_1e6ce0d2_1 | 51.387355 | False |
| interactive_spec_writing_1e6ce0d2_1 | 1.520427 | False |
| cli_fast-details | 1.612856 | False |
| interactive_spec_writing_1e6ce0d2_1 | 1.561024 | False |
| cli_fast-details | 1.454110 | False |
| interactive_scene_planning_1e6ce0d2_1 | 51.455386 | False |
| interactive_spec_writing_1e6ce0d2_1 | 1.699588 | False |
| cli_fast-gate | 0.075461 | False |
| full_quality_wait_after_selection | 0.004649 | False |
| full_quality_reused_after_selection | 0.006106 | True |
| dense_frame_extraction | 2.161893 | False |
| selected_words_1 | 14.833001 | False |
| selected_speech_verification | 32.829167 | False |
| offset_check_1 | 0.402032 | False |
| cli_fast-prepare | 34.964702 | False |
| interactive_selection_reading_c68ab054_1 | 32.754480 | False |
| cli_recheck | 15.154484 | False |
| speech_recovery | 70.540932 | False |
| interactive_scene_planning_c68ab054_1 | 49.048428 | False |
| interactive_spec_writing_c68ab054_1 | 2.663003 | False |
| cli_plan-check | 0.036459 | False |
| cli_review | 41.642461 | False |
| cli_review-inspect | 0.027938 | False |
| cli_review-inspect | 0.036208 | False |
| cli_review-inspect | 0.035273 | False |
| cli_review-inspect | 0.030274 | False |
| cli_review-inspect | 0.027207 | False |
| cli_review-inspect | 0.033913 | False |
| cli_review-inspect | 0.029677 | False |
| cli_review-inspect | 0.038246 | False |
| cli_review-inspect | 0.026541 | False |
| cli_review-inspect | 0.031012 | False |
| cli_review-inspect | 0.038692 | False |
| cli_review-inspect | 0.027245 | False |
| interactive_review_pass_c68ab054_1 | 65.175997 | False |
| interactive_correction_c68ab054_1 | 2.463660 | False |
| cli_review | 35.340800 | False |
| cli_review-inspect | 0.040362 | False |
| cli_review-inspect | 0.037285 | False |
| cli_review-inspect | 0.027162 | False |
| cli_review-inspect | 0.025309 | False |
| cli_review-inspect | 0.029219 | False |
| cli_review-inspect | 0.026881 | False |
| cli_review-inspect | 0.028959 | False |
| interactive_review_pass_c68ab054_2 | 37.133577 | False |
| final_sampling_clip1 | 4.252456 | False |
| cli_render | 43.842302 | False |
| interactive_final_inspection_c68ab054_1 | 42.389672 | False |
| interactive_correction_c68ab054_2 | 2.273979 | False |
| cli_review | 21.531427 | False |
| cli_review-inspect | 0.032914 | False |
| cli_review-inspect | 0.036165 | False |
| cli_review-inspect | 0.031210 | False |
| cli_review-inspect | 0.044743 | False |
| cli_review-inspect | 0.032957 | False |
| cli_review-inspect | 0.031107 | False |
| cli_review-inspect | 0.036543 | False |
| interactive_review_pass_c68ab054_3 | 36.902458 | False |
| final_sampling_clip1 | 4.204607 | False |
| cli_render | 39.355159 | False |
| cli_review-inspect | 0.211907 | False |
| cli_review-inspect | 0.180961 | False |
| cli_review-inspect | 0.164379 | False |
| interactive_final_inspection_c68ab054_2 | 48.007400 | False |

Local preview: `private workflow/jobs/3uYendU1XMk-sections-4796a42a-clip1/reel.mp4`. Output hash: `e469306179ced2265f8ac625f08b94af80efb77843d902369a055f6046dd9f75`. No publishing or main merge.
