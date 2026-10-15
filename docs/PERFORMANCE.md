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
