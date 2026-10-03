"""BUY_PROTECTION (jf_config): an early trip to the Minetown temple to buy AC from its priest (research/protect_buy.md).

priest.c priest_talk: #chat to a peaceful priest in his own temple (any alignment) while carrying gold asks
'How much will you offer?' (minion.c bribe). An offer of 400*XL <= gold < 600*XL gives 'Thou hast been rewarded for thy
devotion.': the first time u.ublessed = rn1(3, 2) = 2-4 points of AC, then +1 per donation (while u.ublessed < 9; up to
20 with a 1/ublessed chance). Every donation costs 400*XL, so the trip pays only at a low XL: a Healer (1001-2000 gold,
u_init.c) at XL 1 buys 4-7 AC (verified in a wizard-mode probe: 2000 gold, AC 9 -> 2 in five chats).

The trip (tour milestone BE_ON_FIRST_LEVEL only, like the pick trip): from the start of the game while
XL <= BUY_PROT_MAX_XL and gold >= 400*XL, go to Mines level 3, then 4 (dungeon.def minetn @ (3, 2)), recognise the town
(priest, watchman, shopkeeper or an altar on Mines 3-4), walk next to the peaceful temple priest and donate 400*XL while
the gold lasts. Then the normal plan resumes (the remaining gold is kept). Aborts: out of time, gold below 400*XL, a
failed prayer, low HP before the town, no town on Mines 3-4, no priest (Orcish Town: an altar, no priest, orcs), a cranky
priest, repeated chat failures.

Prompt sequence (NLE probe): M-c -> 'Talk to whom? (in what direction)' -> direction -> 'The priest of X asks you for a
contribution for the temple.--More--' -> 'How much will you offer?' (text entry) -> '400\\r' -> 'You give the priest of X
400 zorkmids.--More--' -> '"Thou hast been rewarded for thy devotion."'. One game turn per chat.
"""
from __future__ import annotations

import nle.nethack as nh
import numpy as np
from nle.nethack import actions as A

from . import jf_config, utils
from .glyph import G, MON
from .item import Item, flatten_items
from .level import Level
from .strategy import Strategy

PRICE_PER_XL = 400
S_ORC = chr(15)                   # monsym.h S_ORC: permonst.mlet of the orcs

_DIRS = {
    'n': A.CompassDirection.N, 's': A.CompassDirection.S, 'e': A.CompassDirection.E, 'w': A.CompassDirection.W,
    'ne': A.CompassDirection.NE, 'se': A.CompassDirection.SE, 'nw': A.CompassDirection.NW,
    'sw': A.CompassDirection.SW,
}

# priest.c verbalize lines
MSG_REWARDED = 'Thou hast been rewarded for thy devotion'
MSG_GENEROUS = 'Thy selfless generosity is deeply appreciated'   # offer >= 600*XL, or the u.ublessed cap
MSG_PIOUS = 'Thou art indeed a pious individual'                 # 200*XL <= offer < 400*XL
MSG_SMALL = ('Cheapskate', 'I thank thee for thy contribution')  # offer < 200*XL
MSG_CRANKY = ('Thou wouldst have words', 'Here is what I have to say', 'I would speak no longer with thee',
              "doesn't want anything to do with you", 'Thou desecratest this holy place', 'Thou shalt regret')
MSG_NO_GOLD = ('is not interested', 'preaches the virtues of poverty', 'for an ale')
TOWN_NAMES = ('watchman', 'watch captain', 'shopkeeper', 'aligned priest')
MINETOWN_LEVELS = (3, 4)          # Mines-relative level numbers (dungeon.def minetn @ (3, 2))


def price(xl):
    """The smallest offer that buys protection at this XL (priest.c: offer >= u.ulevel * 400)."""
    return PRICE_PER_XL * max(1, int(xl))


def expected_donations(gold, xl):
    return int(gold) // price(xl)


def classify(message):
    """The outcome of one chat from the accumulated message."""
    if MSG_REWARDED in message:
        return 'rewarded'
    if any(m in message for m in MSG_CRANKY):
        return 'cranky'
    if MSG_GENEROUS in message:
        return 'capped'
    if MSG_PIOUS in message or any(m in message for m in MSG_SMALL):
        return 'too_small'
    if any(m in message for m in MSG_NO_GOLD):
        return 'no_gold'
    return 'unknown'


class ProtectionBuyer:
    def __init__(self, agent):
        self.agent = agent
        self.started = None           # turn the trip started
        self.done = False             # the trip is over (bought, aborted or never eligible)
        self.reason = None
        self.donations = 0
        self.stop_buying = False      # no more chats this game (capped, cranky priest, chat failures)
        self.town = None              # level key of Minetown
        self.not_town = set()         # Mines level numbers ruled out
        self.priest_seen = False
        self._level_turns = {}        # Mines 3/4 key -> turns spent there during the trip
        self._last_turn = None
        self._town_since = None       # first turn on the town level during the trip
        self.chat_fails = 0
        self.ac_start = None
        self._mapped = {}             # level key -> turn our magic mapping was read there
        self._map_tried = set()

    # ---- eligibility and the trip state
    def _role_ok(self):
        roles = jf_config.BUY_PROT_ROLES
        if roles is None:
            return True
        role = getattr(self.agent.character, 'role', None)
        from .character import Character
        return any(role == getattr(Character, str(r).upper(), object()) for r in roles)

    def _finish(self, reason):
        if self.done:
            return
        self.done = True
        self.reason = reason
        bl = self.agent.blstats
        self.agent.log(f'PROT trip over: {reason} (donations {self.donations}, AC {self.ac_start} -> '
                       f'{bl.armor_class}, gold {bl.gold}, XL {bl.experience_level}, T{bl.time})')

    def trip_active(self):
        """The tour's protection trip is on (global_logic.tour_strategy targets target_level())."""
        if not jf_config.BUY_PROTECTION or self.done:
            return False
        agent = self.agent
        bl = agent.blstats
        if self.started is None:
            if getattr(agent.character, 'role', None) is None:
                return False   # not parsed yet
            if not self._role_ok():
                self.done, self.reason = True, 'role'
                return False
            if bl.experience_level > jf_config.BUY_PROT_MAX_XL or \
                    bl.gold < price(bl.experience_level) * max(1, jf_config.BUY_PROT_MIN_DONATIONS):
                self._finish(f'not eligible (XL {bl.experience_level}, gold {bl.gold})')
                return False
            if agent.prayer_failed:
                return False
            self.started = bl.time
            self.ac_start = bl.armor_class
            agent.log(f'PROT trip: off to the Minetown temple with {bl.gold} gold at XL {bl.experience_level} '
                      f'({expected_donations(bl.gold, bl.experience_level)} donations of '
                      f'{price(bl.experience_level)})')
            return True
        reason = self.abort_reason()
        if reason is not None:
            self._finish(reason)
            return False
        return True

    def in_town(self):
        try:
            return self.town is not None and self.agent.current_level().key() == self.town
        except Exception:
            return False

    def abort_reason(self):
        agent = self.agent
        bl = agent.blstats
        if self.stop_buying:
            return f'stopped buying ({self.reason or "priest"})' if self.donations == 0 else 'bought'
        if bl.gold < price(bl.experience_level):
            return 'bought' if self.donations else f'gold {bl.gold} below {price(bl.experience_level)}'
        if bl.time - self.started > jf_config.BUY_PROT_TURNS:
            return 'out of time'
        if agent.prayer_failed:
            return 'prayer failed'
        if jf_config.BUY_PROT_ABORT_HP and not self.in_town() and \
                bl.hitpoints < jf_config.BUY_PROT_ABORT_HP * bl.max_hitpoints:
            return f'low HP {bl.hitpoints}/{bl.max_hitpoints}'
        if all(n in self.not_town for n in MINETOWN_LEVELS) and self.town is None:
            return 'no Minetown on Mines 3-4'
        if self._town_since is not None and bl.time - self._town_since > jf_config.BUY_PROT_TOWN_TURNS:
            return 'no priest reached in town'
        if self.chat_fails >= 3:
            return 'chat failures'
        return None

    def target_level(self):
        if self.town is not None:
            return self.town
        for n in MINETOWN_LEVELS:
            if n not in self.not_town:
                return (Level.GNOMISH_MINES, n)
        return None

    # ---- per-step bookkeeping (GlobalLogic.update)
    def _town_glyphs(self):
        return frozenset(MON.from_name(n) for n in TOWN_NAMES)

    def update(self):
        if not jf_config.BUY_PROTECTION or self.done and self.stop_buying:
            return
        agent = self.agent
        try:
            level = agent.current_level()
            bl = agent.blstats
        except Exception:
            return
        if getattr(agent.character.prop, 'hallu', False):
            return
        priest = MON.from_name('aligned priest')
        if level.dungeon_number == Level.GNOMISH_MINES and level.level_number in MINETOWN_LEVELS:
            key = level.key()
            if utils.isin(agent.glyphs, frozenset((priest,))).any():
                self.priest_seen = True
            town = agent.global_logic.minetown_level == key or \
                utils.isin(agent.glyphs, self._town_glyphs()).any() or \
                utils.isin(level.objects, G.ALTAR).any() or bool(getattr(level, 'altars', None))
            if town and self.town is None:
                self.town = key
                agent.log(f'PROT Minetown is {key}')
            if self.started is not None and not self.done:
                if self.town == key and self._town_since is None:
                    self._town_since = bl.time
                if self.town is None:
                    last = self._last_turn if self._last_turn is not None else bl.time
                    self._level_turns[key] = self._level_turns.get(key, 0) + max(0, bl.time - last)
                    # our magic mapping shows the temple's altar (map_strategy): none after 2 turns rules it out
                    mapped = key in self._mapped and bl.time >= self._mapped[key] + 2
                    if (mapped or self._level_turns[key] > jf_config.BUY_PROT_LEVEL_TURNS) and \
                            level.level_number not in self.not_town:
                        self.not_town.add(level.level_number)
                        agent.log(f'PROT Mines level {level.level_number} is not Minetown '
                                  f'({"mapped" if mapped else str(self._level_turns[key]) + " turns"})')
                elif self.town == key and not self.priest_seen and jf_config.BUY_PROT_ORC_TOWN_HOSTILES:
                    # Orcish Town (minetn-1): an altar, no priest, a horde of hostile orcs
                    orcs = [m for m in agent.get_visible_monsters() if getattr(m[3], 'mlet', None) == S_ORC]
                    if len(orcs) >= jf_config.BUY_PROT_ORC_TOWN_HOSTILES:
                        self.stop_buying = True
                        self.reason = 'Orcish Town'
                        self._finish('Orcish Town (hostile orcs, no priest)')
        self._last_turn = bl.time

    # ---- the donation
    def _priest_target(self):
        """(y, x) of the nearest visible peaceful temple priest (an altar within 5 squares), or None."""
        agent = self.agent
        level = agent.current_level()
        priest = MON.from_name('aligned priest')
        mask = (agent.glyphs == priest) & agent.monster_tracker.peaceful_monster_mask
        if not mask.any():
            return None
        altars = set(map(tuple, np.argwhere(utils.isin(level.objects, G.ALTAR))))
        altars |= set(getattr(level, 'altars', {}) or {})
        y0, x0 = agent.blstats.y, agent.blstats.x
        found = []
        for y, x in zip(*mask.nonzero()):
            y, x = int(y), int(x)
            # priest.c: a priest out of his temple turns hostile when talked to (inhistemple)
            if not any(max(abs(ay - y), abs(ax - x)) <= 5 for ay, ax in altars):
                continue
            found.append((max(abs(y - y0), abs(x - x0)), y, x))
        if not found:
            return None
        return min(found)[1:]

    def can_donate(self):
        if not jf_config.BUY_PROTECTION or self.stop_buying or not self._role_ok():
            return False
        if not jf_config.BUY_PROT_ANYTIME and (self.started is None or self.done):
            return False
        agent = self.agent
        bl = agent.blstats
        prop = agent.character.prop
        if getattr(prop, 'hallu', False) or getattr(prop, 'blind', False) or getattr(prop, 'confusion', False):
            return False
        if agent.current_level().dungeon_number not in (Level.DUNGEONS_OF_DOOM, Level.GNOMISH_MINES):
            return False
        if bl.gold < price(bl.experience_level):
            return False
        if bl.hitpoints < jf_config.BUY_PROT_CHAT_HP * bl.max_hitpoints:
            return False
        y0, x0 = bl.y, bl.x
        if any(max(abs(m[1] - y0), abs(m[2] - x0)) <= 2 for m in agent.get_visible_monsters()):
            return False   # fight2 first
        return True

    @Strategy.wrap
    def donate_strategy(self):
        """Next to the peaceful temple priest: #chat and offer 400*XL; else walk next to him."""
        if not self.can_donate():
            yield False
        agent = self.agent
        target = self._priest_target()
        if target is None:
            yield False
        py, px = target
        y0, x0 = agent.blstats.y, agent.blstats.x
        if max(abs(py - y0), abs(px - x0)) > 1:
            dis = agent.bfs()
            near = [(int(dis[y, x]), y, x) for y, x in agent.neighbors(py, px)
                    if dis[y, x] > 0]
            if not near:
                yield False
            yield True
            _, ty, tx = min(near)
            agent.go_to(ty, tx, max_steps=jf_config.BUY_PROT_WALK_STEPS)
            return
        yield True
        self.chat(py, px)

    def chat(self, py, px):
        """One #chat to the priest at (py, px) (adjacent) offering 400*XL. Returns classify()'s outcome."""
        agent = self.agent
        bl = agent.blstats
        amount = price(bl.experience_level)
        gold0, ac0 = bl.gold, bl.armor_class
        if self.ac_start is None:
            self.ac_start = ac0
        action = _DIRS[agent.calc_direction(bl.y, bl.x, py, px)]
        state = {'talk': False, 'asked': False}

        def gen():
            if 'Talk to whom?' not in agent.single_message:
                yield A.Command.ESC
                return
            state['talk'] = True
            yield action
            for _ in range(8):
                if 'How much will you offer?' in agent.single_message:
                    state['asked'] = True
                    yield from str(amount)
                    yield '\r'
                    return
                if agent._observation['misc'][2]:
                    yield ' '
                    continue
                return

        with agent.atom_operation():
            agent.step(A.Command.CHAT, gen())
        message = agent.message or ''
        outcome = classify(message) if state['asked'] or state['talk'] else 'no_talk'
        bl = agent.blstats
        agent.log(f'PROT chat at XL {bl.experience_level}: offered {amount if state["asked"] else 0} '
                  f'({outcome}); gold {gold0} -> {bl.gold}, AC {ac0} -> {bl.armor_class}')
        if outcome == 'rewarded':
            self.donations += 1
            self.chat_fails = 0
        elif outcome in ('cranky', 'capped', 'no_gold'):
            self.stop_buying = True
            self.reason = outcome
        else:
            self.chat_fails += 1
            if self.chat_fails >= 3:
                self.stop_buying = True
                self.reason = 'chat failures'
        return outcome

    # ---- Tourists' magic mapping: tell Mines 3-4 apart at once
    def _map_scroll(self):
        for i in flatten_items(self.agent.inventory.items):
            if i.category == nh.SCROLL_CLASS and i.is_unambiguous() and i.object.name == 'magic mapping' and \
                    i.status != Item.CURSED and i.shop_status == Item.NOT_SHOP:
                return i
        return None

    @Strategy.wrap
    def map_strategy(self):
        """On Mines 3-4 before the town is known: read a known scroll of magic mapping (a Tourist starts with
        four): the altar shows the temple, its absence rules the level out."""
        if not jf_config.BUY_PROTECTION or not jf_config.BUY_PROT_MAGIC_MAP or self.started is None or self.done \
                or self.town is not None:
            yield False
        agent = self.agent
        level = agent.current_level()
        if level.dungeon_number != Level.GNOMISH_MINES or level.level_number not in MINETOWN_LEVELS:
            yield False
        dive = agent.global_logic.dive
        if level.key() in self._map_tried or level.key() in getattr(dive, '_magic_mapped', ()) or \
                self._map_scroll() is None:
            yield False
        prop = agent.character.prop
        if getattr(prop, 'blind', False) or getattr(prop, 'confusion', False) or getattr(prop, 'hallu', False):
            yield False
        yield True
        self._map_tried.add(level.key())
        if dive._read_magic_mapping():
            self._mapped[level.key()] = agent.blstats.time
