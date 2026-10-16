> **Performance branch:** experimental incremental optimizations on `performance-optimization`; main is unchanged. Read [the measured report](docs/PERFORMANCE.md). No end-to-end time target or unattended semantic editing is proved. Existing output/review/publication guards remain.

# AUTO CLIPPING

### Current default: transcript first, selected video only

For stream HTTP 403 errors, an optional local PO-token provider is supported. Run `powershell -File tools/setup_youtube_po.ps1` in an installed clone (or supply `-Python "C:/path/to/python.exe"` and optional `-CaFile "C:/path/to/ca.pem"`). It installs the matching plugin/Node script and prints the non-secret `YOUTUBE_PO_TOKEN_HOME` path to add to your ignored `.env`. Node >=22 is required. No paid service, Docker or GPU is needed. Keep its `workflow/private-provider-cache` private; do not copy it to students. Provider setup is separate from measured per-video runtime and cannot guarantee YouTube access. Read [the official provider instructions](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) for limitations.

`reel.py analyze --url URL --clips 1` now prepares a caption draft or local audio-only transcription before downloading video. After Codex selects a complete 30–60s story, `reel.py fast-prepare JOB --selection SELECTION.json` downloads only that passage plus 3s padding and verifies its words/timing. Full audio may be used for transcription and section-offset anchors; no full video/proxy is needed. Section errors stop rather than silently downloading the whole video.

New jobs use one pre-render visual review, accept reported minor visual defects without correction loops, render once, and do not generate post-render screenshots. Captions, camera style, CTA, technical validation and approval of the exact preview before Instagram publishing remain. These settings are `TRANSCRIPT_FIRST=true` and `SINGLE_PASS_REVIEW=true`. Older workflow examples below describe the retained legacy routes; follow this paragraph for new default YouTube jobs. No fresh speed target has yet been measured for this change.

Create reviewed vertical clips from YouTube videos, working interactively in Codex with a local Python/FFmpeg pipeline. Supply a URL, choose one or two clips, review the actual MP4s, then approve any Instagram post through your own Zernio account.

## Start here

1. Clone this repository and open its folder in Codex.
2. Say **onboarding**. Follow [ONBOARDING.md](ONBOARDING.md) to install Python 3.11, CPU dependencies, FFmpeg/ffprobe, a supported yt-dlp JavaScript runtime, and local speech models. First-time installation/model downloads are additional setup time.
3. Enter your own credentials in the private local `.env`: `ZERNIO_API_KEY`, `ZERNIO_INSTAGRAM_ID`, and `HF_TOKEN` for initial gated speaker-model provisioning. Public YouTube lookup needs no API key. Instagram posting is optional; a supplied YouTube URL can be prepared without Instagram credentials.
4. Send a **YouTube URL**, or say **analyze YouTube** to check your configured channel. Codex asks **one clip or two?** unless you already supplied the count.
5. Codex selects complete moments, reviews character/action framing, renders and validates each clip, and shows the real MP4 preview. If a second moment is weak or impossible under the constraints, it tells you honestly.
6. Only explicit approval of an exact finished preview authorizes its Instagram publication. No automatic post is made during cloning or onboarding.

This is a **Windows-first, Codex-operated workflow**, not an unattended one-command editor. Python prepares media and executes reviewed edit specifications; Codex supplies editorial decisions and actual image inspection. No OpenAI, Groq, AssemblyAI or hosted Hugging Face inference API is used. You still need your own Codex access, local CPU/RAM/disk, and any Zernio plan required by your account.

## Output contract

- Complete 30–60-second story, with the supplied **four-second CTA appended**. Never pad, loop reactions, or cut off a word/payoff to meet a length.
- Full-screen **1080 × 1920, 30fps, H.264/AAC**, libx264 CRF18. Crop the entire source height and move horizontally with **1.2-second easing** and actual scene-cut resets. No generated zoom, fitted landscape, blurred borders or inset.
- Frame the reviewed character, object, action or text relevant to the story. Audio speaker labels never imply a screen position. Impossible full-subject fits remain blockers.
- Roman Hindi/Hinglish preserves actual wording and existing English. Creepster lettering, thick black outline/shadow, white default, timed red spoken-word highlighting, usually two-word phrases, fixed position **(500,1420)**. Verified local word IDs/timing remain mandatory.
- Animated identity passages receive a full first-pass scene review. Stable known non-animated passages may use baseline-only inspection only after all required checks pass with zero flags. Later rounds inspect changed/flagged pages; at most two correction rounds. Final MP4 inspection and exact-preview approval remain required.

[AGENTS.md](AGENTS.md) is the authoritative operator contract; latest rules at its top supersede historical entries. [ARCHITECTURE.md](ARCHITECTURE.md) describes components, preparation routes, evidence, review checks, timing and known limits. [ONBOARDING.md](ONBOARDING.md) covers installation and private account setup.

## Commands

```powershell
# Start directly once the clip count is known; do not separately fetch metadata first.
.venv/Scripts/python.exe reel.py analyze --url YOUTUBE_URL --clips 1
# No URL: use the checkout's configured channel.
.venv/Scripts/python.exe reel.py analyze --clips 2
.venv/Scripts/python.exe reel.py status JOB_ID
.venv/Scripts/python.exe reel.py timing-report JOB_ID
```

Normal analysis uses careful editing semantics: metadata, concurrent highest-quality full transfer for ordinary sources, <=480p proxy and native uploaded/auto selection-only captions or local base/tiny fallback. Selected passages receive local Whisper small/beam5 verification and proxy/final audio anchor checks. Very large/4K sources use selected sections plus one bounded full fallback. Draft captions/proxy pixels never become final caption evidence/final video pixels.

Codex continues with `fast-details`, `fast-gate`, `fast-prepare` (also used by careful preparation), schema-validated `scene-build`, `review`, actual `review-inspect`, `render`, and final inspection. `--fast` is opt-in and changes uncertain-word handling; it never bypasses identity/review/render guards. See architecture and `reel.py --help` for details.

After a human approves the exact preview, the operator may run:

```powershell
.venv/Scripts/python.exe reel.py publish JOB_ID --confirmed
```

Publishing saves idempotency and provider state, polls confirmation, and records the resulting post. Never reset an uncertain pending request to create a second post.

## Private state and sharing

`.env`, cookies, channel connections, jobs, transcripts, downloaded footage, previews, publication records, model weights and virtual environments stay local and are excluded from this repository. Every student uses a separate clone and their own account credentials. The bundled CTA is a supplied generic end card; replace it with your own if desired. Font licenses are included beside the font files.

Use `tools/build_release.py` to prepare an allowlisted student export. It scans for credential patterns and excludes private runtime state. It does not publish a repository or Instagram post. Never commit tokens, cookies or signed upload URLs.

## Validation and limits

```powershell
.venv/Scripts/python.exe -m pytest -q
```

Tests cover downloader bounds, caption caching/fallback, selected verification, identity gates, crop/action safety, review/hash carry-over, timing and publication safeguards. Tests do not establish perfect semantic identity, wording or lip sync on unseen footage. YouTube availability, throttling, cookies, account permissions, hardware and required editorial corrections can block or slow a run. No fixed completion-time guarantee is made. A fresh clone has not been independently benchmarked on every student's machine.

For a stalled selected-section transfer, an explicit bounded recovery is available: `python reel.py fast-prepare JOB --selection SELECTION.json --recover-section`. It preserves partials and verified speech, downloads only the selected range losslessly, and checks source audio anchors again. It does not download the full video. See ARCHITECTURE.md.
