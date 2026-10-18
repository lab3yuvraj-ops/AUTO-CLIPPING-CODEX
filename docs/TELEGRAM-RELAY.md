# Telegram interface to Codex

Persistent mode is the supported student interface. Telegram supplies text to one saved Codex conversation in this project; the existing Python editor remains unchanged. It is separate from the open desktop chat. It does not install that desktop chat's browser tools/plugins or guarantee identical capabilities.

## Student setup

1. Clone the performance-optimization branch and open it in Codex. Say onboarding. Follow ONBOARDING.md for the CPU environment, FFmpeg/ffprobe, yt-dlp runtime and local speech models.
2. Enter your own TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_IDS privately in this clone's ignored .env. Never copy the creator's credentials, connection receipt, jobs, media, approvals or publication state. Zernio credentials are not required to clip a supplied URL.
3. Install requirements-telegram.txt in the project environment. Use an official complete Codex CLI with your own ChatGPT login, not API-key authentication. If the desktop-bundled CLI cannot start the shared server, install the official @openai/codex npm package in tools/vendor/codex-relay and configure its actual executable in TELEGRAM_CODEX_PATH. Windows .cmd/.bat/.ps1 wrappers are not accepted as the executable. Onboarding Codex can locate the installed codex.exe; no creator-specific path is distributed.
4. Start the owned official app-server daemon with REEL_PUBLICATION_DISABLED=true and no AI API-key/provider overrides. This never enables billing. Do not stop another project's active server. Verify the isolated server supports the installed official protocol.
5. Start the persistent relay. The first connection creates its own conversation; later clean starts resume that same ID and history. It never silently resumes the desktop conversation.

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-telegram.txt
# Optional official local CLI provisioning when no complete CLI is installed:
npm install --prefix tools/vendor/codex-relay --no-audit --no-fund @openai/codex@0.163.0
# Configure the actual CLI executable privately, then start the owned daemon:
$env:REEL_PUBLICATION_DISABLED='true'
node tools/vendor/codex-relay/node_modules/@openai/codex/bin/codex.js app-server daemon start
.venv/Scripts/python.exe telegram_relay.py run --persistent
# In another terminal, read-only reachability diagnostics:
.venv/Scripts/python.exe telegram_relay.py doctor --persistent
```

Keep the PC awake, online and the background processes running. A daemon must already be running; the relay never installs or starts it implicitly. No startup task is installed automatically. tools/telegram_startup.ps1 optionally registers persistent mode at logon, and requires the daemon already available; legacy controller startup now requires explicit -LegacyController. Do not run competing pollers.

## Automatic routine decisions

Send a URL or ordinary instructions through Telegram. Incoming text is forwarded verbatim; no routine message-received acknowledgements are sent. An explicit clip count wins; otherwise TELEGRAM_DEFAULT_CLIPS=1. Do not ask routine questions about counts, another moment or ordinary local recovery. When a candidate genuinely cannot work, automatically try up to TELEGRAM_RESELECTION_ATTEMPTS=2 replacement candidates per requested clip (valid 0-2). Reuse successful stages and verify/review changed passages normally. These are agent instructions, not a guarantee of model compliance or unlimited recovery. Missing required consent/credentials/tools or exhausted alternatives produces a precise needs_action/needs_attention report without another routine question. Never bypass actual editorial evidence to avoid reporting a blocker.

Codex may diagnose errors, apply minimal reversible local repairs on performance-optimization, run tests and resume in the same turn. It does not defer ordinary debugging to the desktop. It preserves existing captions, CTA, audio, quality, native speech, review and publication rules. Multiple characters do not automatically require a union box; assess reviewed primary subjects over time and preserve meaning. Indispensable simultaneous action is not waived. Single-pass minor flags are inspected once and disclosed rather than forcing repeated reviews. Actual required subject bounds cannot be invented or narrowed to pass.

Each turn checks this clone's .env presence and exact project Python runtime; secrets never enter the setup summary. TELEGRAM_PYTHON_PATH may explicitly select another verified existing environment. No parent-project credential search is permitted. Reuse working dependencies/models; do not repeat onboarding because an unrelated PATH Python lacks packages. Human-only logins, terms, CAPTCHA and private credential entry still need the owner locally. The transport cannot consent for a student.

## Reliability and privacy

Only allowlisted users in matching private chats are accepted. All users on one relay share one context and project; this is not multi-tenant isolation. /status reports current activity and queue size. Questions are not needed for routine editorial decisions. Only exact transcript/selection/editing milestones return from commentary, once each per turn and only to the initiating sender. Other commentary is suppressed by a code allowlist, not keyword guessing. The relay announces rendered only after validating the saved output hash/checks, then sends the attachment captioned This is the video. Successful preview delivery suppresses the verbose final narrative. Ordinary questions and genuine final blockers still receive answers; saved editorial warnings and upload failures are disclosed briefly. Raw shell output, stderr and credentials are not mirrored. Replies are redacted and split using Telegram's UTF-16 text length limit.

Offsets, queued messages and active turn IDs are private and persisted before work. Duplicate updates do not duplicate turns. Polling has bounded backoff, respects retry_after and stops on authorization/conflicting-poller errors. Failed progress/final text delivery records a safe diagnostic and does not abort the Codex turn or falsely claim delivery. Ambiguous sends are not retried automatically, to avoid duplicates. Check /status and the saved conversation if a message is missing.

A recorded active turn after a crash requires reconciliation rather than an automatic duplicate run. Human-only permission requests are never automatically approved. Configuration/developer instruction updates require reloading the idle owned server and relay; preserve the conversation receipt and never interrupt an active turn for reload. Local tests are not proof every network/provider error can be repaired.

Only actual hash-verified workflow/jobs/CLIP/reel.mp4 exports with passing technical checks and Needs approval status may be sent as previews. Video upload is attempted at most once per sender/render hash automatically. Oversized files remain local, and uncertain uploads are reported without duplication. Incoming Telegram file attachments are not supported yet. This transport is preview-only: it never publishes to Instagram or creates approval.

## Verification boundary

The official CLI/proxy connection uses WebSocket framing, bridged through a local socketpair on Windows Python builds lacking AF_UNIX. No public listener is opened. A live text round trip and a harmless shell/image tool probe passed on the owner machine. Those do not prove an entire Reel completed through Telegram. Provider rate limits, unavailable videos, impossible essential framing and missing human-only evidence can still stop a request safely. A new student installation must run its own diagnostics and harmless connection test.

The earlier telegram_bot.py controller and exact-desktop-thread queue prototype remain available for compatibility but are not the default interface. Same-desktop delivery was unavailable in the tested setup; the owner explicitly approved the dedicated persistent conversation. Do not follow old prototype setup as if it were the supported persistent path.
