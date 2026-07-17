# Forge Echo

A Telegram bot for a single forum-style supergroup. It tracks members as they
join, post, or leave, and lets anyone mention the whole group (or just the
admins) from any topic, with the mention posted into a designated Welcome
topic.

## Features

- Tracks group members automatically via join/leave events and message
  activity, storing them in a local SQLite database.
- Mention trigger (default `@alll`): typed in any topic, reposts the
  message into the Welcome topic and tags every stored member there, except
  the sender.
- Admin mention trigger (default `@admin`): same behavior, but tags only
  the group's current admins, fetched live from Telegram.
- Works correctly in closed topics, since the bot posts as an admin.
- Trigger phrases are configurable so they can be changed if another bot in
  the group happens to use the same plain-text phrase.

## Files

- `v6.py` - the bot itself.
- `backfill_members.py` - a one-time, manually run script for pulling the
  full current member list into the database before the bot has had a
  chance to observe everyone. Not part of the deployed bot.
- `requirements.txt` - dependencies for the deployed bot.
- `.gitignore` - excludes secrets, the database, and the backfill script.

## Setup

1. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

2. Create a `.env` file in the project root:

   ```
   TOKEN=your_bot_token
   WELCOME_TOPIC_ID=1
   TRIGGER_ALL=@alll
   TRIGGER_ADMIN=@admin
   ```

   - `TOKEN` is your bot token from BotFather.
   - `WELCOME_TOPIC_ID` is the thread ID of the Welcome topic. Get it from
     a message link in that topic, e.g. `https://t.me/c/<chat_id>/<topic_id>`.
   - `TRIGGER_ALL` and `TRIGGER_ADMIN` are optional. If omitted, they
     default to `@alll` and `@admin`.

3. Add the bot to the group as an administrator. Admin status alone is
   enough to post in closed topics; no extra rights are required for that.

4. Run the bot:

   ```
   python v6.py
   ```

## One-time member backfill

The Bot API has no endpoint that returns a full member list, so the bot
only learns about people as they join or post. To seed the database with
everyone already in the group, `backfill_members.py` connects as your
personal Telegram account (via Telethon, not the bot) and pulls the full
participant list once.

1. Get `API_ID` and `API_HASH` from https://my.telegram.org, using your
   personal account.

2. Add to the same `.env` file:

   ```
   API_ID=your_api_id
   API_HASH=your_api_hash
   CHANNEL_ID=your_group_channel_id
   ```

   `CHANNEL_ID` is the plain numeric group ID, without the `-100` prefix
   that appears in bot chat IDs. For example, if the bot's stored chat_id
   is `-1003956972838`, `CHANNEL_ID` is `3956972838`.

   Alternatively, set `GROUP_USERNAME` instead of `CHANNEL_ID` to a public
   username or invite link. `CHANNEL_ID` takes priority if both are set.

3. Install Telethon:

   ```
   pip install telethon
   ```

4. Run the script from the same directory as the bot's database:

   ```
   python backfill_members.py
   ```

   On first run it will ask for your phone number, a login code, and your
   two-step verification password if you have one set. This creates a
   local session file so you won't be asked again.

Run this script only when you need a fresh sync, not on a schedule. It
uses a personal account, and Telegram does watch for bulk-scraping
patterns.

## Deployment notes

- This bot uses polling, not webhooks, so it should be deployed as a
  background worker rather than a web service.
- SQLite storage is a plain file on disk. On platforms with an ephemeral
  filesystem (Railway, Render, Fly.io, and similar), attach persistent
  storage and make sure the working directory points at it, or the member
  database will be wiped on every redeploy.
- Only `TOKEN` and `WELCOME_TOPIC_ID` (and optionally `TRIGGER_ALL` /
  `TRIGGER_ADMIN`) need to be set in the deployed environment. `API_ID`,
  `API_HASH`, and `CHANNEL_ID` are only needed to run the backfill script
  locally and should not be part of the deployed bot's configuration.