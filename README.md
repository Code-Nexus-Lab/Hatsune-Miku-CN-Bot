# Hatsune Miku — Code Nexus Bot

Hatsune Miku is the official Discord assistant for Code Nexus. This project is being delivered as tested, deployable feature slices rather than one unverified drop.

## Phase 1: foundation

This release includes secure configuration, SQLite persistence, console and file logging,
a reusable embed system, utility commands, and a complete XP system.

## Requirements

- Python 3.12+
- FFmpeg (required for the music feature in a later phase)
- A Discord application with **Message Content** and **Server Members** intents enabled

## Installation

```bash
git clone <repository-url>
cd code-nexus-bot
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then set `DISCORD_TOKEN`. Never commit `.env`.

```bash
python bot.py
```

## Configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `DISCORD_TOKEN` | Yes | Discord bot token |
| `PREFIX` | No | Command prefix; default `!` |
| `DATABASE_PATH` | No | SQLite file location |
| `LOG_LEVEL` | No | Logging level; default `INFO` |
| `GROQ_API_KEY` | Later | AI API credential |
| `GROQ_MODEL` | Later | Groq model identifier |
| `GITHUB_TOKEN` | Later | Higher GitHub API rate limit |

## Current commands

`!help`, `!ping`, `!about`, `!uptime`, `!userinfo [member]`,
`!serverinfo`, `!rank [member]` (or `!level`), and `!leaderboard`.

Members earn 15–25 XP per message, with a 60-second cooldown. Administrators with
**Manage Server** may use `!setlevel`, `!addxp`, `!removexp`,
`!setlevelrole`, and `!removelevelrole`.

Ask the AI assistant with `!chat <question>` or by mentioning Hatsune Miku.
Each member is limited to one AI request every 15 seconds. The bot retains only
the latest 12 messages in that member's server-specific conversation; use
`!chat clear` to delete them.

## Persistence

First startup creates `data/levels.db`. Its schema covers users, role rewards, challenges, submissions, warnings, guild settings, and music queue state for the feature cogs that follow.

## Deployment

Use a process manager such as systemd, Docker, or Supervisor. Persist `data/`, secure `.env`, and forward `logs/bot.log` to your standard log collection.

## Troubleshooting

- Enable Message Content Intent if commands are ignored.
- Create `.env` beside `bot.py` if startup says `DISCORD_TOKEN` is required.
- Run only one bot process per SQLite file to avoid lock contention.

## Contributing

Use a feature branch, retain type hints and asynchronous I/O, and test changes in a development Discord server before merging.

## License

Select the license that matches Code Nexus's publishing policy before releasing the repository.
