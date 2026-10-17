# Telegram and Codex conversation transport

**Current operational mode:** the owner-approved persistent conversation (see the last section) is connected and its message/reply test passed. The exact existing desktop-chat mode remains unavailable. Do not confuse these modes.

This optional relay forwards private owner text verbatim with the installed official `codex queue --thread UUID --message TEXT`. It never launches `codex exec`, creates a thread, assembles an editorial prompt, picks a model, changes permissions or changes the clipping engine. Use a fixed UUID, never the most recent session or a guessed chat name. The existing conversation determines what the message means and asks for clip count/approval normally.

## Current verification boundary

The installed CLI exposes queue. The official documentation describes queuing to existing sessions: https://developers.openai.com/codex/cli/reference . The app-server protocol documents read-only `thread/read`: https://developers.openai.com/codex/app-server .

Diagnosis and fixes (18 October 2026): the desktop-bundled CLI could not install a daemon because it lacks a complete local package. An isolated official npm `@openai/codex@0.163.0` package was installed under ignored tools/vendor/codex-relay; the desktop binary was untouched. A bounded shared-daemon start succeeded. The old proxy implementation incorrectly sent JSONL: the Unix control endpoint actually requires an HTTP Upgrade and WebSocket framing. The relay now wraps the official raw-byte proxy with websockets through an in-process socketpair; it opens no public listener and works with Windows Python builds lacking AF_UNIX.

A real initialize + thread/read succeeded without generation, resume or queueing. The exact desktop chat was returned as **notLoaded**. This means the new shared daemon has saved history, not the live desktop execution. The relay rejects notLoaded, missing status, systemError and mismatched thread IDs. A saved ID alone never establishes live delivery. **Same-desktop-chat delivery remains unavailable in this tested setup; the relay must remain stopped.** The shared daemon installed solely for diagnosis is stopped afterward.

Do not resume this active desktop thread into a second server to manufacture readiness. The owner must explicitly agree to a persistent server-hosted conversation/handoff (different from the requested live-window transport), or use a supported desktop input connection if one becomes available. No replacement thread, model request, UI keystroke injection, secret-store access or private session-file modification is authorized by a failed check. Starting a daemon alone does not fix desktop message routing.

## Private configuration

In the ignored `.env` set your own TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_IDS (comma-separated positive numeric IDs), actual executable TELEGRAM_CODEX_PATH and TELEGRAM_CODEX_THREAD_ID. Empty TELEGRAM_ALLOWED_USER_IDS retains the single-owner TELEGRAM_ALLOWED_USER_ID behavior. All listed users can send instructions into the SAME shared Codex conversation, with that conversation's permissions and context; this is not tenant isolation. Only explicitly trusted users belong on the allowlist. Do not post real IDs in public examples. Never commit or print credentials. The earlier credentials were removed at the owner's request; re-enter them privately. Keep the old job controller and its startup task stopped. This relay shares its singleton lock to prevent competing pollers.

```powershell
.venv/Scripts/python.exe telegram_relay.py doctor
# Only when the exact existing session is reachable and configured:
.venv/Scripts/python.exe telegram_relay.py run
```

Install the optional transport dependency with `python -m pip install -r requirements-telegram.txt`. Doctor uses initialize and thread/read over WebSocket via the already-running server proxy. No model generation, turn start, Telegram request or message queueing occurs. A missing/unreachable server fails closed. Run never starts or enables a daemon, Windows task, remote endpoint or billing.

This first version is **incoming text only**. Replies, file attachments and operating-system consent stay in Codex. It sends a fixed Telegram queue acknowledgement, never a fabricated assistant answer. A complete two-way Telegram frontend is not yet implemented. No transcripts, session history, credentials, tools or ordinary logs are forwarded to Telegram. Queue messages are passed literally as one process argument; do not send secrets through Telegram (the OS can expose process arguments locally).

Only explicitly allowlisted users in their matching private chats are allowed. Groups, nonmembers, bot senders and sender/chat mismatches are rejected. Each fixed acknowledgement is sent only to the initiating sender, never broadcast. Relay state binds the exact allowlist and session; changing either requires local reconciliation and does not silently reassign existing delivery records. Offset is persisted before delivery. No automatic resend after an uncertain delivery, timeout or restart. Check the Codex conversation before manually resending. Historical updates are discarded once on first startup. Text is not rewritten into a URL-only clipping command. Attachments are rejected explicitly. A failed notification may leave a queued message visible only in Codex. The app must be running/connected and the PC awake/online.

All existing workflow/publication approval rules remain unchanged. A Telegram setup or arbitrary sender is never standing permission to publish. This file introduces no editorial policy and no promised timing improvement.


## Approved persistent conversation mode (18 October 2026)

The owner explicitly approved a persistent Telegram-connected Codex conversation after the live desktop limitation was verified. `python telegram_relay.py run --persistent` uses one new server-hosted conversation in this same project. This is intentionally separate from the desktop chat. It does not fork, resume or migrate the active desktop conversation. The private receipt is workflow/telegram/persistent-conversation.json; do not copy it, the .env or live messages to a student clone.

The background process keeps its official WebSocket connection open. It creates the dedicated thread once and resumes only its own recorded ID on later clean starts. It forwards incoming text verbatim, sequentially, to that conversation; questions and final assistant answers return only to the initiating private user. All four approved users share the same context and permissions, not isolated projects. Owner allowlists remain private. Raw tool output and stderr are never mirrored. Known credential values and key patterns are redacted from assistant replies. Preview-only developer instructions and REEL_PUBLICATION_DISABLED in the owned daemon environment prohibit Instagram publication.

The CLI uses the existing ChatGPT login; no separate paid API key/provider/model is introduced. The default account model remains unchanged. Python/Whisper/OpenCV/FFmpeg rendering stays CPU-only with the existing AGENTS.md workflow and exact output rules. General messages and count answers do not become forced clipping commands. No source code, styling, workflow tests or editorial rules are modified by this transport. Interactive-only approval requests fail for local review; the relay never automatically consents.

Only real hash-verified `workflow/jobs/CLIP/reel.mp4` exports with saved passing technical checks and Needs approval state may be sent as video previews. Oversized files remain local. Video upload is attempted at most once automatically per user/render hash; an uncertain upload is not silently repeated. Nothing is posted on Instagram.

Run preparation (on this machine it has been completed, not a command to run repeatedly):

```powershell
python -m pip install -r requirements-telegram.txt
npm install --prefix tools/vendor/codex-relay --no-audit --no-fund @openai/codex@0.163.0
# Select the installed actual codex.exe privately in TELEGRAM_CODEX_PATH.
# Start the owned daemon with preview-only environment and no API-key variables.
$env:REEL_PUBLICATION_DISABLED='true'
node tools/vendor/codex-relay/node_modules/@openai/codex/bin/codex.js app-server daemon start
python telegram_relay.py run --persistent
```

This setup uses no Windows startup task. Keep the PC awake, online and the background processes running. The desktop window need not stay open for the dedicated conversation. A new process discards historical Telegram commands only on first initialization. On restart with an active recorded turn, it stops for local reconciliation rather than assuming the job ended or retrying it. Transient polling failures use bounded backoff; authorization errors and conflicting pollers stop. Messages saved before a clean shutdown remain queued privately, with update offsets preventing automatic duplicates. Never run legacy telegram_bot.py or the exact-desktop relay simultaneously.

Actual live setup: official complete CLI 0.163.0 installed; owned shared daemon started with publication disabled; persistent thread created successfully without generation; four-user allowlist and long polling initialized. A harmless Telegram message/reply test and real source clipping must be identified separately from setup and mocked tests. No YouTube download or Instagram publication was performed during connection repair.

Live transport test completed: the owner sent the requested connection-test message in Telegram; the exact prompt was present in the dedicated Codex session, the model returned exactly connected, and the Telegram send completed while the controller remained ready. This consumed one Codex-account turn (27,832 input tokens, including 13,440 cached; 5 output). No AI API key, YouTube transfer, Reel render or Instagram publication was used in this test. A real clipping run through this persistent transport has not yet been tested.


## Student .env and runtime detection

The student sets their own private credentials locally in this clone once. The persistent session reads a fresh setup snapshot before every message, including .env presence, configured-key booleans, the project Python interpreter, saved-channel presence, and read-only reel.py doctor results. Secret values are used only by existing project commands and in-memory outgoing redaction, never included in model-visible setup summaries. Editing commands are unchanged.

Use `.venv/Scripts/python.exe` from this checkout; TELEGRAM_PYTHON_PATH can explicitly select an already installed environment. No automatic parent-directory secret search or cross-student credential import occurs. Missing packages are tested in that exact interpreter. A configured environment/model cache skips duplicate onboarding and installation. Zernio/Instagram is optional for URL clipping. A saved channel is needed only for channel triggers. If actual credentials are absent, the bot names the missing fields and directs the student to the local private editor; it never requests tokens/passwords in Telegram.

Owner-machine repair: this working checkout's incomplete environment was preserved privately and replaced with a local junction to the owner's existing CPU environment. Three missing credential entries were restored from the same owner's original local project by explicit user request. This is private local repair, not a student template/default or export. No secret, absolute owner environment path, connection or approval is distributed to students.
