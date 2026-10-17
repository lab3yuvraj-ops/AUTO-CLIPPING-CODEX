# Telegram as input for an existing Codex session

This optional relay forwards private owner text verbatim with the installed official `codex queue --thread UUID --message TEXT`. It never launches `codex exec`, creates a thread, assembles an editorial prompt, picks a model, changes permissions or changes the clipping engine. Use a fixed UUID, never the most recent session or a guessed chat name. The existing conversation determines what the message means and asks for clip count/approval normally.

## Current verification boundary

The installed CLI exposes queue. The official documentation describes queuing to existing sessions: https://developers.openai.com/codex/cli/reference . The app-server protocol documents read-only `thread/read`: https://developers.openai.com/codex/app-server .

Local read-only checking could not connect to the shared daemon control socket. The existing desktop app is not yet proved to expose this chat to that daemon. **Desktop delivery is not verified and the relay is not connected or started.** Starting a separate daemon is not proof that a message reaches the same desktop conversation. Do not resume this thread in a separate CLI as a workaround, start a replacement session, edit session files or use UI typing to disguise this limitation. Resolve the supported desktop/shared-server connection, then check the exact UUID. A successful read-only check proves visibility only; a supervised harmless test must still confirm the message appears in the intended desktop conversation.

## Private configuration

In the ignored `.env` set your own TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_ID, actual executable TELEGRAM_CODEX_PATH and TELEGRAM_CODEX_THREAD_ID. Never commit or print credentials. The earlier credentials were removed at the owner's request; re-enter them privately. Keep the old job controller and its startup task stopped. This relay shares its singleton lock to prevent competing pollers.

```powershell
.venv/Scripts/python.exe telegram_relay.py doctor
# Only when the exact existing session is reachable and configured:
.venv/Scripts/python.exe telegram_relay.py run
```

Doctor uses initialize and thread/read via the already-running server proxy. No model generation, turn start, Telegram request or message queueing occurs. A missing/unreachable server fails closed. Run never starts or enables a daemon, Windows task, remote endpoint or billing.

This first version is **incoming text only**. Replies, file attachments and operating-system consent stay in Codex. It sends a fixed Telegram queue acknowledgement, never a fabricated assistant answer. A complete two-way Telegram frontend is not yet implemented. No transcripts, session history, credentials, tools or ordinary logs are forwarded to Telegram. Queue messages are passed literally as one process argument; do not send secrets through Telegram (the OS can expose process arguments locally).

Only the configured private owner is allowed. Offset is persisted before delivery. No automatic resend after an uncertain delivery, timeout or restart. Check the Codex conversation before manually resending. Historical updates are discarded once on first startup. Text is not rewritten into a URL-only clipping command. Attachments are rejected explicitly. A failed notification may leave a queued message visible only in Codex. The app must be running/connected and the PC awake/online.

All existing workflow/publication approval rules remain unchanged. A Telegram setup or arbitrary sender is never standing permission to publish. This file introduces no editorial policy and no promised timing improvement.
