# CardBot — a UNO-style Telegram bot

## Setup
1. Talk to @BotFather: `/newbot` and copy the token.
2. Enable inline mode: `/setinline` (set a placeholder like "Your cards").
3. **Important:** `/setinlinefeedback` → choose **Enabled** (100%). Without this the bot is never told which card you tapped.
4. Allow the bot in groups: `/setjoingroups` → Enable. Also `/setprivacy` → Disable is not required (commands work with privacy on).
5. Run:

```bash
pip install -r requirements.txt
export BOT_TOKEN="123456:ABC..."   # Windows PowerShell: $env:BOT_TOKEN="..."
python bot.py
```

## Commands
| Command | Who | What |
|---|---|---|
| `/new` | anyone | create a game (you become host) |
| `/join` / `/leave` | anyone | join/leave (joining mid-game deals 7 cards) |
| `/start` | players | start with 2+ players (in private chat: shows help) |
| `/skip` | anyone | skip a player who took more than 90s (they draw 1 card) |
| `/notify_me` | anyone | toggle DM when a game starts |
| `/settings` | anyone | show settings |
| `/kick`, `/remove` | host or group admin | reply to a player's message to remove them |
| `/close`, `/open`, `/kill` | host or group admin | lobby control / end game |
| `/status` | host only | per-player card counts, whose turn, wait time, deck sizes |

`/status` shows card counts only, never the actual cards, so the host can't peek at hands.

## Notes
- Cards are played through inline mode: type `@yourbot ` in the group. ⛔ cards are unplayable.
- Games live in memory and are lost on restart (add SQLite/Redis later).
- Only English texts for now; `/enable_translations` is a placeholder.
- Multi-group play is not implemented: one game per user at a time.
- "UNO" is a Mattel trademark. Use your own bot name and artwork if you publish it.
