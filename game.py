"""Game engine for a UNO-style card game. No Telegram dependencies."""
import random
import time

COLORS = ["r", "g", "b", "y"]
COLOR_EMOJI = {"r": "🔴", "g": "🟢", "b": "🔵", "y": "🟡", "x": "🌈"}
COLOR_NAME = {"r": "Red", "g": "Green", "b": "Blue", "y": "Yellow"}
VALUE_LABEL = {"skip": "Skip", "reverse": "Reverse", "draw2": "+2",
               "wild": "Wild", "draw4": "Wild +4"}
HAND_SIZE = 7
TURN_TIMEOUT = 90  # seconds before /skip is allowed


class GameError(Exception):
    pass


def card_name(card):
    color, value = card
    return f"{COLOR_EMOJI[color]} {VALUE_LABEL.get(value, value)}"


def card_code(card):
    return f"{card[0]}:{card[1]}"


def build_deck():
    deck = []
    for c in COLORS:
        deck.append((c, "0"))
        for v in [str(i) for i in range(1, 10)] + ["skip", "reverse", "draw2"]:
            deck += [(c, v)] * 2
    deck += [("x", "wild")] * 4 + [("x", "draw4")] * 4
    return deck  # 108 cards


class Player:
    def __init__(self, uid, name):
        self.id = uid
        self.name = name
        self.hand = []


class Game:
    def __init__(self, chat_id, host_id, host_name):
        self.chat_id = chat_id
        self.host_id = host_id
        self.players = []
        self.draw_pile = []
        self.discard = []
        self.current = 0
        self.direction = 1
        self.color = None
        self.started = False
        self.open = True
        self.drawn = False
        self.winner = None
        self.translations = False
        self.turn_started = time.time()
        self.add_player(host_id, host_name)

    # ---- lookups ----
    def get(self, uid):
        for p in self.players:
            if p.id == uid:
                return p
        return None

    @property
    def current_player(self):
        return self.players[self.current]

    @property
    def top(self):
        return self.discard[-1]

    # ---- lobby ----
    def add_player(self, uid, name):
        if self.get(uid):
            raise GameError("You are already in this game.")
        p = Player(uid, name)
        self.players.append(p)
        if self.started:  # late joiners are dealt in
            self._draw_cards(p, HAND_SIZE)
        return p

    def remove_player(self, uid):
        p = self.get(uid)
        if p is None:
            raise GameError("That player is not in the game.")
        i = self.players.index(p)
        self.draw_pile[0:0] = p.hand  # hand goes to bottom of the deck
        p.hand = []
        self.players.pop(i)
        if uid == self.host_id and self.players:
            self.host_id = self.players[0].id
        if not self.started or not self.players:
            self.current = 0
            return
        if i < self.current:
            self.current -= 1
        elif i == self.current:
            if self.direction == -1:
                self.current -= 1
            self.drawn = False
            self.turn_started = time.time()
        self.current %= len(self.players)

    def start(self):
        if self.started:
            raise GameError("The game has already started.")
        if len(self.players) < 2:
            raise GameError("You need at least 2 players to start.")
        self.draw_pile = build_deck()
        random.shuffle(self.draw_pile)
        for p in self.players:
            p.hand = [self.draw_pile.pop() for _ in range(HAND_SIZE)]
        while True:  # first card must be a plain number card
            card = self.draw_pile.pop()
            if card[1].isdigit():
                break
            self.draw_pile.insert(0, card)
        self.discard = [card]
        self.color = card[0]
        self.started = True
        self.current = 0
        self.direction = 1
        self.drawn = False
        self.turn_started = time.time()

    # ---- rules ----
    def can_play(self, card):
        if card[0] == "x":
            return True
        return card[0] == self.color or card[1] == self.top[1]

    def _check_turn(self, player):
        if self.winner:
            raise GameError("The game is over.")
        if self.current_player is not player:
            raise GameError("It's not your turn.")

    def _draw_cards(self, player, n):
        got = []
        for _ in range(n):
            if not self.draw_pile:
                if len(self.discard) <= 1:
                    break
                top = self.discard.pop()
                self.draw_pile = self.discard
                self.discard = [top]
                random.shuffle(self.draw_pile)
            card = self.draw_pile.pop()
            player.hand.append(card)
            got.append(card)
        return got

    def _advance(self, steps=1):
        self.current = (self.current + self.direction * steps) % len(self.players)
        self.drawn = False
        self.turn_started = time.time()

    def play(self, player, card, chosen=None):
        """Play a card. Returns a list of event strings (consequences)."""
        self._check_turn(player)
        if card not in player.hand:
            raise GameError("You don't have that card.")
        if not self.can_play(card):
            raise GameError("You can't play that card right now.")
        if card[0] == "x" and chosen not in COLORS:
            raise GameError("Pick a color for the wild card.")
        player.hand.remove(card)
        self.discard.append(card)
        self.color = chosen if card[0] == "x" else card[0]
        events = []
        if not player.hand:
            self.winner = player
            return events
        if len(player.hand) == 1:
            events.append(f"🔔 UNO! {player.name} has one card left!")
        v = card[1]
        if v == "skip":
            self._advance(1)
            events.append(f"🚫 {self.current_player.name} is skipped")
            self._advance(1)
        elif v == "reverse":
            self.direction *= -1
            if len(self.players) == 2:
                events.append("↩️ Reverse (acts as a skip with 2 players)")
                self._advance(2)
            else:
                events.append("↩️ Direction reversed")
                self._advance(1)
        elif v in ("draw2", "draw4"):
            n = 2 if v == "draw2" else 4
            self._advance(1)
            victim = self.current_player
            got = self._draw_cards(victim, n)
            events.append(f"➕ {victim.name} draws {len(got)} cards and loses the turn")
            self._advance(1)
        else:
            self._advance(1)
        return events

    def draw(self, player):
        self._check_turn(player)
        if self.drawn:
            raise GameError("You already drew a card. Play it or pass.")
        got = self._draw_cards(player, 1)
        self.drawn = True
        if not got:
            self._advance(1)
            return [f"{player.name} couldn't draw (deck empty) and passes"]
        if not any(self.can_play(c) for c in player.hand):
            self._advance(1)
            return [f"{player.name} can't play the drawn card and passes"]
        return []

    def pass_turn(self, player):
        self._check_turn(player)
        if not self.drawn:
            raise GameError("Draw a card first.")
        self._advance(1)
        return []

    def seconds_waiting(self):
        return time.time() - self.turn_started

    def skip_current(self):
        p = self.current_player
        self._draw_cards(p, 1)
        self._advance(1)
        return [f"⏰ {p.name} took too long and draws a card"]

    # ---- display ----
    def status(self):
        top = self.top
        parts = []
        for i, p in enumerate(self.players):
            mark = "▶️ " if i == self.current else ""
            parts.append(f"{mark}{p.name} ({len(p.hand)})")
        return (
            f"🃏 Top card: {card_name(top)}\n"
            f"🎨 Color: {COLOR_EMOJI[self.color]} {COLOR_NAME[self.color]}\n"
            f"👉 Turn: {self.current_player.name}\n"
            f"👥 " + ", ".join(parts)
        )

    def host_status(self):
        """Detailed overview for the host. Card counts only, never hands."""
        lines = [f"👑 Host view — {'in progress' if self.started else 'lobby'}"
                 f" ({'open' if self.open else 'closed'})"]
        for i, p in enumerate(self.players):
            tag = []
            if p.id == self.host_id:
                tag.append("host")
            if self.started and i == self.current:
                tag.append(f"playing, waiting {int(self.seconds_waiting())}s")
            extra = f" [{', '.join(tag)}]" if tag else ""
            cards = f"{len(p.hand)} cards" if self.started else "joined"
            lines.append(f"{i + 1}. {p.name}: {cards}{extra}")
        if self.started:
            lines.append(f"Top: {card_name(self.top)} | color {COLOR_NAME[self.color]}")
            lines.append(f"Deck: {len(self.draw_pile)} | Discard: {len(self.discard)}")
        return "\n".join(lines)
