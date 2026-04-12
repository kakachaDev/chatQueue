# chatQueue

A Telegram bot for managing a scheduled post queue in a channel.

Call `/posts` the day before — the bot shows interactive cards for tomorrow's posts. Each card can be edited, approved, or skipped. At the scheduled time, the bot publishes approved posts to the channel automatically.

## Installation

```bash
git clone https://github.com/kakachaDev/chatQueue.git
cd chatQueue
./setup.sh
```

`setup.sh` creates a virtual environment, installs dependencies, and copies `.env.example` to `.env`.

## Configuration

Fill in `.env`:

```env
BOT_TOKEN=123456789:AAxxxxxx
CHANNEL_ID=@your_channel
ADMIN_USER_ID=123456789
```

- `BOT_TOKEN` — token from [@BotFather](https://t.me/BotFather). The bot must be an admin of the channel with posting rights.
- `CHANNEL_ID` — channel username (`@name`) or numeric ID.
- `ADMIN_USER_ID` — your Telegram ID (get it from [@userinfobot](https://t.me/userinfobot)).

`config.json`:

```json
{
  "start_date": "2026-05-01",
  "reminder_time": "21:00"
}
```

- `start_date` — the date that corresponds to `day: 1` in `posts.json`.
- `reminder_time` — time (MSK) to send a reminder if tomorrow's posts are still unreviewed.

## Post Schedule

Create `posts.json` based on `posts.json.example`:

```json
{
  "schedule": [
    { "day": 1, "time": "10:00", "text": "post text" },
    { "day": 1, "time": "21:00", "text": "second post on the same day" },
    { "day": 2, "time": "12:00", "text": "post on the next day" }
  ]
}
```

`day: 1` = `start_date`, `day: 2` = `start_date + 1 day`, and so on. Times are in Moscow time.

## Running

```bash
./start.sh   # start in background
./stop.sh    # stop
tail -f bot.log  # logs
```

The watchdog loop inside `start.sh` restarts the bot after 10 seconds if it crashes.

## Auto-start on reboot

```bash
crontab -e
```

Add:

```
@reboot /full/path/to/chatQueue/start.sh
```

## Usage

**`/posts`** — shows post cards for tomorrow. On first call, creates them. On repeat calls, refreshes them (deletes old cards, sends fresh ones at the bottom of the chat).

Buttons on each card:

| Button | Action |
|---|---|
| ✏️ Text | Edit post text. Telegram formatting (bold, italic, etc.) is preserved. |
| 🕐 Time | Change publication time (MSK, format HH:MM) |
| ✅ Approve | Queue the post for publication |
| ⏭ Skip | Skip the post |
| ↩️ Back to pending | Undo approval or skip |
| 🚀 Publish now | Publish immediately (available after approval) |
| ❌ Cancel | Exit editing mode |

All interaction happens inside the card — no extra messages. User input is deleted from the chat automatically.

## Files

| File | Description |
|---|---|
| `posts.json` | Post schedule (create from `posts.json.example`) |
| `posts.json.example` | Example schedule format |
| `config.json` | Settings (start_date, reminder_time) |
| `.env` | Secrets — do not commit |
| `.env.example` | Config template |
| `state.json` | Post statuses — auto-generated |
| `bot.log` | Logs (rotation: 5 MB × 3 files) |
