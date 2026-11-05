import logging
import os

from telegram import (
    InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from telegram.ext import (
    Application,
    ChosenInlineResultHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
)

from game import (
    COLORS, COLOR_EMOJI, COLOR_NAME, TURN_TIMEOUT,
    Game, GameError, card_code, card_name,
)

logging.basicConfig(level=logging.INFO)

games: dict[int, Game] = {}      # chat_id -> Game
user_game: dict[int, int] = {}   # user_id -> chat_id
notify: set[int] = set()         # users who want a DM when a game starts

HELP = """Steps:
1. Add this bot to a group
2. In the group, start a game with /new or join a running one with /join
3. With at least two players, start with /start
4. Type @{bot} in the chat box and hit space (or tap the "via @{bot}" text). You'll see your cards (⛔ = can't play now), draw/pass, and ❓ for the game state. Tap an option to play it.

Players can join at any time. Leave with /leave. If a player takes more than {t} seconds, use /skip. /notify_me sends you a private message when a new game starts.

Settings: /settings
Host or group admin only:
/close - close the lobby
/open - open the lobby
/kill - end the game
/kick or /remove - reply to a player's message to remove them
/enable_translations, /disable_translations - reserved (English only for now)
Host only:
/status - see every player's state (card counts, whose turn, wait time)
"""


# ---------- helpers ----------
def find_game(uid):
    return games.get(user_game.get(uid))


def end_game(game: Game):
    games.pop(game.chat_id, None)
    for uid in [u for u, c in user_game.items() if c == game.chat_id]:
        user_game.pop(uid, None)


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        m = await context.bot.get_chat_member(
            update.effective_chat.id, update.effective_user.id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


async def is_host_or_admin(update, context, game: Game) -> bool:
    return update.effective_user.id == game.host_id or await is_admin(update, context)


async def need_game(update: Update):
    game = games.get(update.effective_chat.id)
    if game is None:
        await update.message.reply_text("No game here. Start one with /new.")
    return game


async def announce(context, game: Game, events):
    """Post the consequences of a move plus whose turn is next."""
    lines = list(events)
    if game.winner:
        lines.append(f"🏆 {game.winner.name} wins the game! 🎉")
        end_game(game)
    else:
        lines.append(game.status())
    await context.bot.send_message(game.chat_id, "\n".join(lines))


# ---------- commands ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_text(
            HELP.format(bot=context.bot.username, t=TURN_TIMEOUT))
        return
    game = await need_game(update)
    if not game:
        return
    if game.get(update.effective_user.id) is None:
        await update.message.reply_text("Join first with /join.")
        return
    try:
        game.start()
    except GameError as e:
        await update.message.reply_text(str(e))
        return
    await update.message.reply_text(
        "🎮 The game has started! Everyone got 7 cards.\n"
        f"Type @{context.bot.username} and a space to see your cards.\n\n"
        + game.status())


async def new_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Add me to a group and use /new there.")
        return
    if chat.id in games:
        await update.message.reply_text("A game is already running here. Use /join.")
        return
    if user.id in user_game:
        await update.message.reply_text("You're already in a game. /leave it first.")
        return
    game = Game(chat.id, user.id, user.full_name)
    games[chat.id] = game
    user_game[user.id] = chat.id
    await update.message.reply_text(
        f"🃏 New game created by {user.full_name} (host).\n"
        "Others can join with /join. Start with /start once 2+ players joined.")
    for uid in list(notify):
        if uid != user.id:
            try:
                await context.bot.send_message(uid, f"A new game started in {chat.title}.")
            except Exception:
                pass  # user never opened a private chat with the bot


async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    game = await need_game(update)
    if not game:
        return
    if not game.open:
        await update.message.reply_text("The lobby is closed.")
        return
    if user.id in user_game and user_game[user.id] != game.chat_id:
        await update.message.reply_text("You're already in a game in another chat.")
        return
    try:
        game.add_player(user.id, user.full_name)
    except GameError as e:
        await update.message.reply_text(str(e))
        return
    user_game[user.id] = game.chat_id
    note = " They were dealt 7 cards." if game.started else ""
    await update.message.reply_text(f"✅ {user.full_name} joined.{note}")


async def leave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    game = await need_game(update)
    if not game:
        return
    await remove_and_report(update, context, game, user.id, "left the game")


async def remove_and_report(update, context, game: Game, uid: int, verb: str):
    p = game.get(uid)
    if p is None:
        await update.message.reply_text("That player isn't in this game.")
        return
    name = p.name
    game.remove_player(uid)
    user_game.pop(uid, None)
    if not game.players:
        end_game(game)
        await update.message.reply_text(f"{name} {verb}. No players left, game closed.")
    elif game.started and len(game.players) < 2:
        winner = game.players[0].name
        end_game(game)
        await update.message.reply_text(
            f"{name} {verb}. Only {winner} is left, so the game ends. 🏆 {winner} wins!")
    elif game.started:
        await update.message.reply_text(f"{name} {verb}.\n\n{game.status()}")
    else:
        await update.message.reply_text(f"{name} {verb}.")


async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = await need_game(update)
    if not game:
        return
    if not game.started:
        await update.message.reply_text("The game hasn't started yet.")
        return
    wait = game.seconds_waiting()
    if wait < TURN_TIMEOUT:
        await update.message.reply_text(
            f"{game.current_player.name} still has {int(TURN_TIMEOUT - wait)}s left.")
        return
    events = game.skip_current()
    await announce(context, game, events)


async def kick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = await need_game(update)
    if not game:
        return
    if not await is_host_or_admin(update, context, game):
        await update.message.reply_text("Only the host or a group admin can remove players.")
        return
    reply = update.message.reply_to_message
    if reply is None or reply.from_user is None:
        await update.message.reply_text("Reply to the player's message with /kick.")
        return
    target = reply.from_user.id
    if target == game.host_id:
        await update.message.reply_text("The host can't be kicked.")
        return
    await remove_and_report(update, context, game, target, "was removed from the game")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = await need_game(update)
    if not game:
        return
    if update.effective_user.id != game.host_id:
        await update.message.reply_text("Only the host can use /status.")
        return
    await update.message.reply_text(game.host_status())


async def close_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_open(update, context, False)


async def open_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_open(update, context, True)


async def set_open(update, context, value: bool):
    game = await need_game(update)
    if not game:
        return
    if not await is_host_or_admin(update, context, game):
        await update.message.reply_text("Only the host or a group admin can do that.")
        return
    game.open = value
    await update.message.reply_text("🔓 Lobby opened." if value else "🔒 Lobby closed.")


async def kill_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = await need_game(update)
    if not game:
        return
    if not await is_host_or_admin(update, context, game):
        await update.message.reply_text("Only the host or a group admin can end the game.")
        return
    end_game(game)
    await update.message.reply_text("🛑 Game terminated.")


async def notify_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in notify:
        notify.discard(uid)
        await update.message.reply_text("🔕 Notifications off.")
    else:
        notify.add(uid)
        await update.message.reply_text(
            "🔔 You'll get a private message when a game starts.\n"
            "(Open a private chat with me and press Start first, or I can't message you.)")


async def translations_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = await need_game(update)
    if not game:
        return
    if not await is_host_or_admin(update, context, game):
        await update.message.reply_text("Only the host or a group admin can do that.")
        return
    game.translations = update.message.text.startswith("/enable")
    await update.message.reply_text(
        "Saved. Note: this starter only has English texts.")


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    on = update.effective_user.id in notify
    await update.message.reply_text(
        "Settings\nLanguage: English (only one available)\n"
        f"Game notifications: {'on' if on else 'off'} (toggle with /notify_me)")


# ---------- inline mode ----------
def article(rid, title, text, desc=None):
    return InlineQueryResultArticle(
        id=rid, title=title, description=desc,
        input_message_content=InputTextMessageContent(text))


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.inline_query
    user = q.from_user
    game = find_game(user.id)
    results = []
    if game is None or not game.started:
        results.append(article(
            "none", "No game running",
            "I'm not in a running game. Use /new or /join in a group chat.",
            "Use /new or /join in a group, then /start"))
        await q.answer(results, cache_time=0, is_personal=True)
        return

    player = game.get(user.id)
    my_turn = game.current_player is player
    nope = []
    if my_turn:
        for card in dict.fromkeys(player.hand):  # unique, keeps order
            count = player.hand.count(card)
            label = card_name(card) + (f" ×{count}" if count > 1 else "")
            if game.can_play(card):
                if card[0] == "x":
                    for col in COLORS:
                        results.append(article(
                            f"{card_code(card)}:{col}",
                            f"{label} → {COLOR_EMOJI[col]} {COLOR_NAME[col]}",
                            f"{user.full_name} played {card_name(card)} "
                            f"and chose {COLOR_EMOJI[col]} {COLOR_NAME[col]}"))
                else:
                    results.append(article(
                        card_code(card), label,
                        f"{user.full_name} played {card_name(card)}"))
            else:
                nope.append(article(
                    f"nope-{card_code(card)}", f"⛔ {label}",
                    f"{user.full_name} looked at an unplayable card.",
                    "You can't play this now"))
        if game.drawn:
            results.append(article("pass", "⏭ Pass", f"{user.full_name} passes"))
        else:
            results.append(article("draw", "🎴 Draw a card",
                                   f"{user.full_name} draws a card"))
    else:
        results.append(article(
            "wait", f"⏳ Waiting for {game.current_player.name}",
            f"{user.full_name} is waiting for {game.current_player.name}.",
            f"{len(player.hand)} cards in your hand"))
        for card in dict.fromkeys(player.hand):
            nope.append(article(
                f"nope-{card_code(card)}", f"⛔ {card_name(card)}",
                f"{user.full_name} looked at an unplayable card.", "Not your turn"))
    results.append(article("status", "❓ Game state", game.status(),
                           f"Top: {card_name(game.top)}"))
    results += nope
    await q.answer(results[:50], cache_time=0, is_personal=True)


async def chosen_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = update.chosen_inline_result
    user, rid = r.from_user, r.result_id
    game = find_game(user.id)
    if not game or not game.started:
        return
    if rid in ("none", "wait", "status") or rid.startswith("nope-"):
        return
    player = game.get(user.id)
    try:
        if rid == "draw":
            events = game.draw(player)
        elif rid == "pass":
            events = game.pass_turn(player)
        else:
            parts = rid.split(":")
            card = (parts[0], parts[1])
            color = parts[2] if len(parts) > 2 else None
            events = game.play(player, card, color)
    except GameError as e:
        await context.bot.send_message(game.chat_id, f"⚠️ {user.full_name}: {e}")
        return
    await announce(context, game, events)


def main():
    token = os.environ["BOT_TOKEN"]
    app = Application.builder().token(token).build()
    commands = {
        "start": start_cmd, "help": start_cmd, "new": new_cmd, "join": join_cmd,
        "leave": leave_cmd, "skip": skip_cmd, "kick": kick_cmd, "remove": kick_cmd,
        "status": status_cmd, "close": close_cmd, "open": open_cmd,
        "kill": kill_cmd, "notify_me": notify_cmd, "settings": settings_cmd,
        "enable_translations": translations_cmd,
        "disable_translations": translations_cmd,
    }
    for name, fn in commands.items():
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(ChosenInlineResultHandler(chosen_result))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
