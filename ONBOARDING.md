# Student onboarding

Open your own clone as a project in Codex and say **onboarding**. Each student has a separate local checkout, private `.env`, channel and processing history. The repository contains no creator credentials, channel connection, saved videos or local model weights.

Codex should perform the setup, not just display instructions: inspect the existing installation, open Chrome with supported browser/computer-use tools, guide your own account access, install missing dependencies and prepare models. Follow [browser-assisted onboarding](docs/BROWSER-ONBOARDING.md). Routine clicks can be handled by Codex. You may still need to sign in, complete 2FA/CAPTCHA, personally accept model-access terms/contact sharing, or approve a service/Windows permission. A clone cannot bypass those requirements or install browser-control tools automatically. Never send passwords or tokens in chat.

## First-time installation (Windows)

Use Python 3.11, Git, FFmpeg/ffprobe and a supported yt-dlp JavaScript runtime such as Node.js. From the repository folder in PowerShell:

```powershell
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install --upgrade pip
.venv/Scripts/python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.venv/Scripts/python.exe -m pip install -r requirements-local.txt
Copy-Item .env.example .env
```

Do not overwrite an existing `.env`. This workflow currently uses Windows process locking; other platforms need that part adapted before use. CPU/int8 is the supported default; no GPU or paid inference API is required. Model downloads are a one-time setup and depend on your connection and machine.

## Connect your accounts

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

Send a **YouTube URL** or say **YouTube analyze**. Codex asks how many clips you want, checks your saved channel, downloads/transcribes the source, reviews all of it, and chooses complete moments. If an additional clip is weaker, it explains why and asks before creating it. Tracking, full-height horizontal framing, smooth movement, locked Hinglish captions and the four-second CTA follow `AGENTS.md`.

You receive the actual MP4 and the question **“Do you want to upload this video to Instagram?”** Clear approval of that exact preview authorizes publication. Codex polls the same Zernio request until it confirms a post ID/link. Saying no leaves the clip local. No dashboard, hosted worker or background schedule is created.

## Sharing on GitHub

Use `tools/build_release.py` to prepare a clean, allowlisted repository folder and ZIP under ignored `release/`. It includes code, docs, tests, licensed fonts, the supplied CTA and blank configuration templates. It excludes `.env`, cookies, connections, saved jobs, private footage, model weights, virtual environments and publication records. The CTA is shared intentionally as the project's supplied end card; students may replace it with their own.

Authenticate GitHub locally with `gh auth login` or your Git credential manager. Do not put a personal access token into a remote URL or files. If a token was pasted into chat, revoke it after the authorized repository operation and create a fresh credential for future use. Never distribute the creator's token.

## Performance branch diagnostics

Run `.venv/Scripts/python.exe reel.py doctor` before the first analysis. It reports missing packages/tools/assets and model-cache presence without sending network requests or printing credentials. Install missing items using the existing instructions above; it does not install software automatically.

`PROCESSING_MODE=smart` is default; `fast` reduces representative static/moving sample density through the same pipeline. This setting is separate from the opt-in `--fast` skipped-word policy. Captions, required reviews and final quality settings remain unchanged. No VLM is required for the existing Codex-operated workflow. Optional semantic endpoint settings are described in ARCHITECTURE.md; model quality, CPU cost and remote provider charges are not guaranteed. Do not configure a paid endpoint unless you intend to use that provider. No endpoint is called by default.
