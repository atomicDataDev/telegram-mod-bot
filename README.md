# Telegram Moderator Bot V5

A multi-purpose Telegram bot for group moderation: automatic new-member approval flow, admin tools, interactive duels, and a daily reputation system in one project.

## Why This Project Is Useful

- automates first-step moderation for new members
- gives admins fast commands for chat management
- adds game mechanics to improve community engagement
- runs on SQLite and does not require a separate DB server

## Features

- Auto-moderation for new members with approve/ban buttons.
- Moderation commands: `lock`, `unlock`, `mute`, `ban`, `warn`, `pending`, and more.
- Interactive duels with rules configurable via bot private chat.
- Reputation system with a `1 vote per day` limit.
- Local SQLite storage with no external infrastructure required.

## Project Structure

- `bot.py` - main Telegram bot file and command handlers.
- `database.py` - SQLite data layer and table operations.
- `config.py` - local runtime configuration.
- `config.example.py` - config template for publishing and first launch.
- `.env` - local secrets/runtime parameters, must not be committed.
- `.env.example` - example environment variables for setup.
- `modbot.db` - local database created automatically, should not be committed.

## Quick Start

1. Install Python 3.11+.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` from `.env.example` and set:
- `BOT_TOKEN` - Telegram bot token from BotFather
- `OWNER_ID` - your Telegram user ID
- `DB_PATH` - SQLite path if you do not want the default location
4. Run the bot:

```bash
python bot.py
```

## Main Commands

### Group Chat Commands

- `/help` - show commands
- `/lock` and `/unlock` - close/open chat
- `/lockmedia` and `/unlockmedia` - disable/enable media
- `/lockpin` and `/unlockpin` - disable/enable pin actions
- `/mute`, `/unmute`, `/kick`, `/ban`, `/unban`
- `/warn`, `/resetwarns`, `/pending`, `/settings`
- `/duel`, `/duelstats`, `/myduel`, `/banduel`, `/unbanduel`
- `/rep`, `/myrep`, `/toprep`

### Bot Private Chat Commands

- `/config` - edit global bot settings
- `/addadmin <user_id>` - add bot admin
- `/removeadmin <user_id>` - remove bot admin
- `/admins` - list bot admins

## License

This project is released under the MIT License. See `LICENSE`.
