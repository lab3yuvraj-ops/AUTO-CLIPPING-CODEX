# Private Telegram → existing Codex Reel workflow

## Investigation and selected architecture

The existing editor is not a Python-only pipeline. `reel.py analyze` resolves the supplied URL or `workflow/connection.json`, saves a transcript draft and a new source job. Codex reads the transcript, selects a complete moment, runs selected preparation, views actual source frames, writes the scene table/spec, inspects one pre-render review and invokes the renderer. Python/Whisper/OpenCV/FFmpeg preserve the existing verification, crop/caption/CTA and technical checks. Validated exports are recorded in `workflow/jobs/CLIP_JOB/job.json` as `video` plus `render_sha256`. Default files are `workflow/jobs/CLIP_JOB/reel.mp4`. No fixed-output/demo implementation was found in the tracked project; none is used here.

The optional transport uses the official non-interactive Codex CLI, not keyboard typing into the desktop app and not an imitation editor. `codex exec --json --output-schema ... -o ... -` receives a fixed prompt on stdin with only a validated canonical video URL and bounded integer clip count interpolated. It executes in this repository, loads AGENTS.md and uses the existing commands/tools. Telegram gathers the count before starting the CLI; no model turn is wasted asking a known question and no running CLI stdin conversation is assumed. The desktop window need not remain open. The bot process, Windows account, local CLI login, PC/network and local models must be available. This is a separate Codex session, not this chat's history or its app-specific tool connection.

Observed locally without generation: Codex CLI 0.163.0-alpha.10.2 has `exec`, JSON event streaming, schema/final-file options, workspace sandbox, and saved ChatGPT authentication. Offline prompt inspection succeeded but did not expose a verifiable shell/image tool inventory. **Headless image/execution equivalence has NOT been proved.** No real workflow or model generation was run during implementation. The bot therefore refuses real jobs until an explicitly authorized capability probe has observed an actual shell execution and actual image-view event and checked a written fixture/result. The fixture is not a Reel/demo output. If this CLI version does not emit recognizable image-tool events, the probe fails closed; do not manually forge its receipt. Diagnose the actual event contract or use the interactive desktop workflow. A passing fixture proves tools, not real-video editorial quality; the first end-to-end run still requires explicit authorization and existing reviews.

Official references inspected: [Codex non-interactive execution](https://developers.openai.com/codex/noninteractive), [CLI reference](https://developers.openai.com/codex/cli/reference), [Telegram getUpdates](https://core.telegram.org/bots/api#getupdates), [Telegram sendVideo](https://core.telegram.org/bots/api#sendvideo). CLI docs specify JSONL/structured output, saved authentication and permissions. They do not promise that every desktop tool is available headlessly. Telegram cloud uploads currently allow video files up to 50 MB; this implementation uses a conservative configurable maximum of 49,000,000 bytes and never silently recompresses your final export.

## Install and configure on Windows

Use the existing Python 3.11 environment and installation/model setup in ONBOARDING.md. This integration adds **no Python dependency and no AI API key**: `httpx`, `python-dotenv`, Pillow and the existing standard library are sufficient. Install/sign into a Codex CLI supporting the required options using your own Codex account. It uses that account's usage limits; it is not unlimited/free compute. It rejects API-key CLI authentication and strips explicit API-key variables from the child. It does not add paid inference or change models. Media remains CPU-only. Do not run another manual clipping job in this checkout while Telegram is working.

From the repository in PowerShell:

```powershell
# Existing environment; if absent, follow ONBOARDING.md first.
.venv/Scripts/python.exe -m pip install -r requirements-local.txt
codex --version
codex login status
# If needed: codex login  (sign in using your own ChatGPT account)
notepad .env
```

Add only these missing values in the private `.env`; preserve every existing channel/model/account value:

```dotenv
TELEGRAM_BOT_TOKEN=YOUR_PRIVATE_BOT_TOKEN
TELEGRAM_ALLOWED_USER_ID=YOUR_NUMERIC_USER_ID
TELEGRAM_CODEX_PATH=codex
TELEGRAM_JOB_TIMEOUT_SECONDS=3600
TELEGRAM_MAX_CLIPS=5
TELEGRAM_UPLOAD_MAX_BYTES=49000000
```

`TELEGRAM_CODEX_PATH` may be the actual absolute Codex `.exe` path. Shell wrappers/custom shell commands are not accepted. Do not use a raw API key, enable paid providers, disable the sandbox, or bypass review to make a probe pass.

Create the bot by opening Telegram's official **@BotFather**, running `/newbot`, and following its naming prompts. Paste its token directly into your ignored `.env`, never into chat/Git/command arguments. For your numeric ID, either use an already trusted Telegram account-information method or run the optional identification command locally **before** starting the bot:

```powershell
# Send /start to your own new bot, then:
.venv/Scripts/python.exe telegram_bot.py identify
```

It reads private-message sender IDs from the official API and prints IDs only, without running jobs or sending messages. Stop other pollers first. Copy your own numeric ID to `.env`; the running controller accepts only that sender in the matching private chat. Never use a username as the allowlist. A new bot start intentionally discards old queued commands; send a fresh trigger after it starts. No webhook is created/deleted automatically; an existing webhook or second poller causes a clear conflict stop.

## Offline checks, then authorized tool probe

```powershell
.venv/Scripts/python.exe telegram_bot.py doctor
.venv/Scripts/python.exe -m pytest -q tests/test_telegram_bridge.py
```

Doctor runs local CLI help/login checks and existing media diagnostics only, never generation, YouTube downloads or Telegram requests. `ready=false` is expected before account configuration/probe. It does not print credentials or silently enable broader permissions.

**Only after the owner explicitly authorizes the small Codex usage/tool probe**, run:

```powershell
.venv/Scripts/python.exe telegram_bot.py probe --authorize-codex-probe
.venv/Scripts/python.exe telegram_bot.py doctor
```

The probe consumes a small real Codex turn against green-image/shell fixtures, not a full video job. No Telegram sends, download, transcription, account connection or Instagram publication. It uses workspace-write plus network permission for subsequent real workflow compatibility, approval policy never (unavailable permissions become failures, not bypasses). `workflow/telegram/capability.json` binds successful observed tools to this project implementation and CLI version/path. Updates invalidate it. A missing tool, denied operation, unavailable account or missing model access must be resolved locally, not fabricated. This probe has not been run as part of implementation.

## Start and everyday use

After the probe passes and you authorize real clipping:

```powershell
.venv/Scripts/python.exe telegram_bot.py run
```

Send **Analyze my YouTube** (uses your existing saved channel) or an HTTPS YouTube video URL. The bot asks **How many clips do you want?** Reply `1`, `2`, etc., up to the configured cap. The controller passes it to a new Codex session and reports only actual session/job status events. It never forwards raw model messages, commands, provider responses or stderr that might contain secrets. A successful process exit is insufficient: output must be a fresh request-bound source/child job, selected count/source/channel must match, all selected children must finish, technical checks and review/hash bindings must exist, and the actual final file must match its saved render hash. No pre-existing video/demo can be returned as this request's result.

The controller uploads the real MP4 bytes with `sendVideo`; no arbitrary file path from a Telegram message is accepted. It retains final MP4s through the existing cleanup policy. A too-large output remains local; Telegram reports its project-relative location, without lowering quality. No automatic Instagram publication exists in this adapter, even if someone replies “good to go.” Use the normal explicit exact-preview approval workflow separately in Codex after testing. Both CLI `publish` and provider writes have a preview-only environment guard in controller runs.

Commands: `/status`, `/help`, `/cancel` (pending clip-count question only), `/resend` (explicitly retry saved MP4 delivery; never re-run clipping). Telegram lacks an idempotency key for video sends: a lost upload acknowledgement may mean the video was delivered. Such uploads stop as `delivery_uncertain`; inspect Telegram before `/resend`, which may duplicate a Telegram message. Uploads are never automatically repeated. Update offsets and launch state are persisted before actions, preventing duplicate updates/restarts from automatically launching a second job. Notification failures may require `/status`/a repeated count. Count collection survives restart.

Only one bot/controller instance per checkout is allowed. A second active request is rejected. Workflow timeout stops the child process tree and retains artifacts; unconfirmed termination writes a blocking marker. If the bot itself crashes while the CLI runs, it records `interrupted` on restart and never assumes the child stopped or automatically repeats work. Inspect the recorded PID and request/job records locally; confirm all descendants have stopped, then reconcile/reset that private controller request locally with Codex. Do not clear live state blindly. There is deliberately no Telegram arbitrary-command/reset endpoint. Human-only speech/identity/permission questions cause needs-attention failure and require local Codex intervention; this preserves the existing safeguards instead of guessing. Zero-interaction success on every source is not guaranteed.

Private state: `workflow/telegram/controller.json`, `requests/REQUEST_ID/response.json`, schema and sanitized execution metadata (usage counters, observed-tool flags, exit code); existing source job timing/phase/review records retain workflow progress. Raw Codex event content/stderr is not logged or forwarded. Codex itself maintains its normal private session history; this bridge does not export it. Failed worker termination marker/PID is private. No credentials enter public release files.

## Start when Windows signs in (optional)

Register only after a successful supervised setup/probe and authorized real test:

```powershell
powershell -File tools/telegram_startup.ps1
# Remove the current-checkout task later:
powershell -File tools/telegram_startup.ps1 -Remove
```

This creates a current-user, non-admin Task Scheduler logon task using this clone's `.venv/Scripts/pythonw.exe`. It does not run as SYSTEM, store passwords, open a public port, disable sleep or start a clipping job. It starts the controller after sign-in, not before login. Keep the PC awake and online; closing the Codex desktop window is fine. Changing/moving the clone requires updating the task; a removed model/environment or expired CLI login requires repair. No startup task was registered during implementation.

## Validation boundary

Mock tests cover private owner/URL/count checks, duplicate offsets/restart handling, actual-runner invocation, request-bound validated output, missing/changed/oversized files, redacted errors, polling quota backoff, ambiguous delivery, no-generation doctor, and preview-only publication guards. They do not prove real headless visual review, YouTube access, model availability, Telegram delivery or end-to-end timing. No real bot token, real Telegram request, real AI generation, video job or publication was used during implementation.
