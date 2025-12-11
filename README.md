# 🐱 Neko Album Maker Bot

A simple and elegant Telegram bot that organizes your media into beautiful albums!

## ✨ Features

- 📸 **Easy Album Creation** - Send media and create albums instantly
- 🎬 **Multiple Media Types** - Support for photos, videos, documents, animations, and audio
- 🔄 **Auto-Grouping** - Automatically groups media into Telegram albums (max 10 items per group)
- ⚡ **Smart Detection** - Automatically detects when you're done sending (2-second timeout)
- 📂 **Database Channel** - Automatically forwards media to a database channel with user info

## Setup

1. Create a bot and get the token from @BotFather.
2. Copy the token into a `.env` file at the project root with the variable `TELEGRAM_BOT_TOKEN`:

```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
```

3. (Optional) Use a venv, then install dependencies:

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r "requirements.txt"
```

## Run

```powershell
python bot.py
```

## How to Use

1. **Start the bot** - Send `/start` to see the welcome message
2. **Send media** - Upload as many media files as you want
3. **Wait or click Done** - Either wait 2 seconds or manually click "Done✅, Make album!"
4. **Get your album** - Media is automatically grouped into albums (max 10 per group) and sent back!

## Commands

- `/start` - Start the bot and see welcome message.
- `/help` - Show detailed help.
- `/clear` - Clear all pending media and start fresh.

## How It Works

- **Automatic Detection**: After 2 seconds of no new media, the Done button appears
- **Manual Control**: Click "Done✅, Make album!" to start processing immediately
- **Smart Grouping**: Media is automatically organized into groups of up to 10 items (Telegram album limit)
- **Per-Chat State**: Multiple users can use the bot simultaneously without interference

## Notes

- Voice messages are sent individually (Telegram limitation - can't be in albums)
- Supports both individual media and media albums
- Use `/clear` to cancel current batch and start fresh
- All processing is done per-chat, so no interference between users

## Usage Example

1. Send 25 photos to the bot
2. Wait ~2 seconds (or click the button)
3. Bot automatically creates 3 albums (10 + 10 + 5 items)
4. All albums sent back to you organized and ready!
