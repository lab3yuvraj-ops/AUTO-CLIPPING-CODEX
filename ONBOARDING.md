# Student onboarding

Open your own clone as a project in Codex and say **onboarding**. Each student has a separate local checkout, private `.env`, channel and processing history. The repository contains no creator credentials, channel connection, saved videos or local model weights.

Codex should perform the setup, not just display instructions: inspect the existing installation, open Chrome with supported browser/computer-use tools, guide your own account access, install missing dependencies and prepare models. Follow [browser-assisted onboarding](docs/BROWSER-ONBOARDING.md). Routine clicks can be handled by Codex. You may still need to sign in, complete 2FA/CAPTCHA, personally accept model-access terms/contact sharing, or approve a service/Windows permission. A clone cannot bypass those requirements or install browser-control tools automatically. Never send passwords or tokens in chat.

## Telegram student checklist (current)

Cloning downloads project code, fonts, CTA and configuration templates only. It does **not** install Python, FFmpeg, Node, packages, model weights, Codex authentication or private credentials. Open the clone in Codex and say **onboarding, including Telegram**. Codex checks existing setup and performs missing installation using this guide; the student completes required login, model terms, CAPTCHA/2FA or OS consent personally.

1. Install/verify Git, Python 3.11, FFmpeg/ffprobe, Node and Codex with the student's own ChatGPT login. Run tools/setup_local.ps1 for CPU packages, and prepare the local speech models. Reuse a working installation.
2. Create the student's own bot with Telegram @BotFather, and enter TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_IDS (numeric sender IDs) in the clone's private .env. No secrets go into Telegram messages to the clipping bot. Instagram/Zernio is optional for clipping; a channel is optional for a supplied URL.
3. Follow docs/TELEGRAM-RELAY.md to configure the complete official Codex CLI, optional transport dependencies and owned preview-only daemon. Start telegram_relay.py run --persistent. Press Start in the student's own bot. The PC must stay awake and online.
4. Before calling setup ready, run reel.py doctor, confirm offline model loading with reel.py prepare-models, run telegram_relay.py doctor --persistent, and verify one harmless Telegram text round trip. These checks do not prove YouTube download access or a completed Reel. Do not start a full clipping test without a source request.
5. Send a YouTube URL (one clip by default, or specify a count). Routine recovery is automatic and bounded. Normal clipping messages are only transcript complete, clips selected, editing, rendered, and the video attachment. Internal command/review chatter stays local. A genuine blocker, upload failure or material quality warning is still reported briefly; the bot must not hide failure or pretend a preview exists.

The Telegram transport currently delivers previews only; it does not post to Instagram, even with configured credentials. Existing exact-preview publication approval rules remain mandatory for any separate supported publication flow.

## Reuse existing private setup first

Before requesting credentials or installing anything, inspect THIS checkout's ignored `.env`, local `.venv`/explicit TELEGRAM_PYTHON_PATH, cached models and saved channel. Report presence/readiness only, never values. Existing valid configuration is reused. Do not search parent folders or copy a creator's/another student's keys, connections, approvals or jobs into a clone. Each student enters their own credentials once in the private local editor; not Telegram or public chat.

The persistent Telegram conversation receives a fresh presence/readiness snapshot before each message. It uses the configured project interpreter, not whichever system Python is on PATH. Missing Zernio/Instagram credentials do not block clipping a supplied URL, and a saved channel is required only for channel-based triggers. If setup is incomplete, name only the missing fields/components and finish it locally in Codex. Never ask the student to repeat credentials through Telegram or rerun onboarding just because the wrong interpreter lacks packages.

## First-time installation (Windows)

Use Python 3.11, Git, FFmpeg/ffprobe and a supported yt-dlp JavaScript runtime such as Node.js. From the repository folder in PowerShell:

Codex runs `powershell -File tools/setup_local.ps1` once Python 3.11 is available (optional `-Python C:/path/to/python.exe`). This creates/reuses the private environment, installs CPU dependencies, checks package/import compatibility and removes only its own `workflow/install-cache` on success. It does not install system tools or account/model access; continue those steps below. Failed installation keeps the cache for recovery. Existing global pip/npm caches and model weights remain untouched. The individual commands below are the manual alternative; use `--no-cache-dir` on their pip invocations to avoid accumulating new installation downloads.

```powershell
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install --upgrade pip
.venv/Scripts/python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.venv/Scripts/python.exe -m pip install -r requirements-local.txt
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
```

Do not overwrite an existing `.env`. This workflow currently uses Windows process locking; other platforms need that part adapted before use. CPU/int8 is the supported default; no GPU or paid inference API is required. Model downloads are a one-time setup and depend on your connection and machine.

## Connect your accounts

For the optional Telegram interface, follow [the current persistent-conversation setup](docs/TELEGRAM-RELAY.md), not the legacy job controller. Codex configures the student's own private token/allowlist and complete official CLI. Telegram defaults to one clip, honors explicit counts and selects bounded replacement moments without routine questions. Missing human-only login/terms/credentials still require the student locally; no secret belongs in Telegram. No daemon, logon task or real generation is started by documentation or mocked tests alone.

1. Tell Codex which YouTube channel URL or channel ID to use. Public channel lookup requires no YouTube API key.
2. Connect your own Instagram account in Zernio. Enter `ZERNIO_API_KEY` and `ZERNIO_INSTAGRAM_ID` in the private local `.env` editor. The ID is Zernio's connected account `_id`, not your Instagram username or numeric Instagram ID. Never paste secrets into chat or commit them. [Zernio account connection guide](https://docs.zernio.com/guides/connecting-accounts), [account verification API](https://docs.zernio.com/accounts/list-accounts).
3. Run the following, replacing `CHANNEL_URL_OR_ID`:

```powershell
.venv/Scripts/python.exe reel.py onboarding --channel CHANNEL_URL_OR_ID --from-env
```

The command verifies that the Instagram account is accessible to your Zernio key, saves your channel in ignored `workflow/connection.json`, and installs the four-second CTA default. It makes no post. Running without `--from-env` provides a hidden terminal key prompt instead. Never supply API keys as command-line arguments.

## Prepare local transcription once

Codex opens [pyannote Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) in Chrome and checks your own account's access. Sign in and personally accept any required access conditions/contact sharing. Codex can then navigate [Hugging Face access tokens](https://huggingface.co/settings/tokens) and help configure a read-only token with the least permissions needed for the model. Existing suitable credentials are reused; do not create a replacement unnecessarily. Save it as `HF_TOKEN` in private `.env` using a supported private transfer, local editor or hidden terminal prompt, never ordinary chat/tool output. Then Codex runs:

```powershell
.venv/Scripts/python.exe reel.py prepare-models --download
```

This downloads Whisper small and the approved speaker model locally. The selection-only base/tiny fallback may also download its model on first use; label this as setup, not inference or a cached speed gain. Later analysis uses cached models offline; HF_TOKEN is for gated model provisioning, not hosted inference. After preparation, `reel.py prepare-models` checks offline model loading. OpenAI, Groq and AssemblyAI keys are not used.

If YouTube challenges downloads, configure an authorized cookie-file path in `YOUTUBE_COOKIE_FILE`; cookie files are private and must never be shared in Git. A blocked download remains a real blocker, not a simulated successful job.

## Everyday use

In desktop Codex, send a **YouTube URL** or say **YouTube analyze** and provide the clip count when asked. In Telegram, one clip is the default and explicit counts are honored without routine questions. A channel is needed only for channel triggers. Codex follows the current transcript-first selection and one-review policy, and reports honestly when too few strong moments exist. Tracking, full-height horizontal framing, smooth movement, locked Hinglish captions and the four-second CTA follow `AGENTS.md`.

You receive the actual MP4 and the question **“Do you want to upload this video to Instagram?”** Clear approval of that exact preview authorizes publication. Codex polls the same Zernio request until it confirms a post ID/link. Saying no leaves the clip local. No dashboard, hosted worker or background schedule is created.

## Sharing on GitHub

Completed transcript-first YouTube jobs automatically delete generated working media once every selected clip is rendered and technically valid. Final MP4s and lightweight specs, verified words, review/timing records and publishing state remain. A later edit may need to download the source section again. Set `AUTO_CLEANUP_COMPLETED=false` before rendering, or explicitly use `--keep-lossless`, to keep intermediates. Failed/active jobs retain recovery files. `reel.py cleanup-completed JOB_ID` retries a safely deferred cleanup; `reel.py cleanup-install-cache` removes only this project's installation cache. Neither command removes models/credentials or publishes.

Use `tools/build_release.py` to prepare a clean, allowlisted repository folder and ZIP under ignored `release/`. It includes code, docs, tests, licensed fonts, the supplied CTA and blank configuration templates. It excludes `.env`, cookies, connections, saved jobs, private footage, model weights, virtual environments and publication records. The CTA is shared intentionally as the project's supplied end card; students may replace it with their own.

Authenticate GitHub locally with `gh auth login` or your Git credential manager. Do not put a personal access token into a remote URL or files. If a token was pasted into chat, revoke it after the authorized repository operation and create a fresh credential for future use. Never distribute the creator's token.

## Performance branch diagnostics

Run `.venv/Scripts/python.exe reel.py doctor` before the first analysis. It reports missing packages/tools/assets and model-cache presence without sending network requests or printing credentials. Install missing items using the existing instructions above; it does not install software automatically.

`PROCESSING_MODE=smart` is default; `fast` reduces representative static/moving sample density through the same pipeline. This setting is separate from the opt-in `--fast` skipped-word policy. Captions, required reviews and final quality settings remain unchanged. No VLM is required for the existing Codex-operated workflow. Optional semantic endpoint settings are described in ARCHITECTURE.md; model quality, CPU cost and remote provider charges are not guaranteed. Do not configure a paid endpoint unless you intend to use that provider. No endpoint is called by default.
