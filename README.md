# Forge Echo

A Telegram group bot that lets admins broadcast a message to everyone (or just the
admins) it has seen active in the chat, with real notifications for users who don't
have a `@username`.

## Features

### `/echo` — mention everyone
Admins can end any message with `/echo` to broadcast it to every member the bot
has on record for that chat.

```
Meeting moved to 6pm /echo
```
Sends:
```
Meeting moved to 6pm

@alice @bob [Charlie]
```
(`Charlie` has no username, so he's tagged with a real inline mention that still
notifies him — see "Notifications that actually work" below.)

If you leave no text before `/echo`, it defaults to **"Attention everyone"**.

### `/echo admin` — mention admins only
Same idea, but only pings chat admins:
```
Need a decision on the venue /echo admin
```

### Admin-only enforcement
Both commands check the sender against Telegram's live admin list for the chat.
Non-admins get:
```
Only admins can use this command.
```

### Automatic member tracking
The bot builds its own roster of the chat over time — there's no manual setup.
A user is added to the database when:
- they send any message in the group, or
- they join, get promoted, or are otherwise added (via Telegram's `chat_member`
  update)

A user is removed automatically when they leave or are kicked.

> **Note:** Telegram's Bot API doesn't let bots list a chat's full existing
> membership. The bot can only learn about members through the events above, so
> coverage builds up as the group is active — it won't magically know about
> silent members who joined before the bot did and never post. See
> [Limitations](#limitations).

### Notifications that actually work
Users with a `@username` are tagged the normal way (`@username`). Users without
one are tagged using a `tg://user?id=...` inline link, which still pings them —
plain text names alone don't notify anyone, so this was specifically built to
avoid silently skipping usernameless members.

### Batched sending
Broadcasts are sent in batches of 5 mentions per message, with a 1-second pause
between batches, to stay under Telegram's rate limits on large groups. If the
sender is included in the member list, they're skipped so they don't get pinged
in their own broadcast.

### Resilient to failures
- If sending one batch fails (e.g. flood control, a user blocked the bot), the
  bot logs it and keeps sending the remaining batches instead of crashing.
- Network drops (e.g. your internet going out) are caught by a global error
  handler and logged as a single line instead of a full traceback; the bot's
  polling loop retries automatically and resumes once connectivity returns.
- Non-group chats (DMs, channels) are ignored safely instead of raising an
  error.

### Local persistence
Member data is stored in a local SQLite database (`database.db`), created
automatically on first run. No external database setup required.

## Requirements

- Python 3.10+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- **Group Privacy mode turned OFF** for your bot in BotFather (`/mybots` → your
  bot → Bot Settings → Group Privacy → Turn off). Without this, the bot can't
  see normal group messages, only commands directed at it.
- The bot added to your group **as an admin**, so it can check the admin list
  and reliably receive join/leave events.

## Setup

1. Install dependencies:
   ```bash
   pip install python-telegram-bot python-dotenv
   ```

2. Create a `.env` file in the project folder (never commit this):
   ```
   TOKEN=your_bot_token_here
   ```

3. Run the bot:
   ```bash
   py v4.py
   ```
   You should see:
   ```
   Database connected
   Bot running...
   ```

## `.gitignore`

Make sure your repo excludes:
```
.env
database.db
venv/
__pycache__/
```

## Limitations

- **No backfill for pre-existing silent members.** The Telegram Bot API has no
  endpoint to list a group's full membership — the bot only learns about users
  through messages sent or `chat_member` events. Members who joined before the
  bot and never post remain invisible until they do something the bot can see.
- **Suffix-based trigger.** `/echo` and `/echo admin` are matched by checking if
  the message *ends with* those strings, not as a strict command — a message
  that incidentally ends the same way will also trigger it.
- **Single group focus.** Data is tracked per `chat_id`, so it works across
  multiple groups the bot is in, but there's no cross-group aggregation or
  admin dashboard.

## Security notes

- Never commit your bot token. It belongs only in `.env`, which is gitignored.
- If a token is ever exposed (committed, pasted in a log, shared in chat),
  revoke it immediately via BotFather (`/mybots` → your bot → API Token →
  Revoke current token) and update `.env` with the new one.
