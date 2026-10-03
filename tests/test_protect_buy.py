"""Unit tests (fakes, no NetHack games) for BUY_PROTECTION (nhbot/protect_buy.py, research/protect_buy.md).
Run from the repo root:  python tests/test_protect_buy.py"""
import contextlib
import os
import sys

import numpy as np
from nle.nethack import actions as A

sys.path.insert(0, os.getcwd())

from nhbot import jf_config                                   # noqa: E402
from nhbot import protect_buy as PB                           # noqa: E402
from nhbot.character import Character                         # noqa: E402
from nhbot.glyph import MON, SS                               # noqa: E402
from nhbot.level import Level                                 # noqa: E402

PRIEST = MON.from_name('aligned priest')
HILL_ORC = MON.from_name('hill orc')
H, W = 21, 79


class BL:
    def __init__(self, xl=1, gold=1500, hp=12, maxhp=12, y=10, x=40, time=1, ac=8):
        self.experience_level, self.gold = xl, gold
        self.hitpoints, self.max_hitpoints = hp, maxhp
        self.y, self.x, self.time, self.armor_class = y, x, time, ac


class Lvl:
    def __init__(self, dnum=Level.DUNGEONS_OF_DOOM, dlevel=1):
        self.dungeon_number, self.level_number = dnum, dlevel
        self.objects = np.full((H, W), -1, dtype=np.int16)
        self.altars = {}

    def key(self):
        return (self.dungeon_number, self.level_number)


class Prop:
    hallu = blind = confusion = False


class Char:
    def __init__(self, role=Character.HEALER):
        self.role = role
        self.prop = Prop()


class Tracker:
    def __init__(self):
        self.peaceful_monster_mask = np.zeros((H, W), bool)


class Dive:
    def __init__(self):
        self._magic_mapped = set()
        self.reads = 0

    def _read_magic_mapping(self):
        self.reads += 1
        return True


class GL:
    def __init__(self):
        self.minetown_level = None
        self.dive = Dive()


class Inv:
    items = []


class FakeAgent:
    """Simulates the NLE chat prompts: CHAT -> 'Talk to whom?' -> direction -> contribution --More-- ->
    'How much will you offer?' (text entry) -> amount + Enter -> priest.c's answer for that amount."""

    def __init__(self, role=Character.HEALER, **bl):
        self.blstats = BL(**bl)
        self.character = Char(role)
        self.prayer_failed = False
        self.level = Lvl()
        self.glyphs = np.zeros((H, W), dtype=np.int16)
        self.monster_tracker = Tracker()
        self.global_logic = GL()
        self.inventory = Inv()
        self.logs, self.calls = [], []
        self.message = self.single_message = ''
        self._observation = {'misc': np.zeros(3, dtype=np.int8)}
        self.hostiles = []
        self.priest_mode = 'peaceful'     # what the priest answers: peaceful / cranky
        self.ublessed = 0

    def current_level(self):
        return self.level

    def log(self, msg):
        self.logs.append(msg)

    def get_visible_monsters(self):
        return self.hostiles

    def bfs(self):
        dis = np.full((H, W), 5, dtype=np.int32)
        dis[self.blstats.y, self.blstats.x] = 0
        return dis

    def neighbors(self, y, x):
        return [(y + dy, x + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]

    def go_to(self, y, x, max_steps=None):
        self.calls.append(('go_to', y, x, max_steps))

    @staticmethod
    def calc_direction(y0, x0, y, x):
        return {(0, 1): 'e', (0, -1): 'w', (1, 0): 's', (-1, 0): 'n',
                (1, 1): 'se', (1, -1): 'sw', (-1, 1): 'ne', (-1, -1): 'nw'}[(y - y0, x - x0)]

    @contextlib.contextmanager
    def atom_operation(self):
        yield

    def _show(self, msg, more=False, text=False):
        self.single_message = msg
        self.message = (self.message + ' ' + msg).strip()
        self._observation['misc'][:] = (0, int(text), int(more))

    def step(self, action, gen=None):
        assert action == A.Command.CHAT, action
        self.calls.append(('chat',))
        self.message = ''
        self._show('Talk to whom? (in what direction)')
        d = next(gen)
        self.calls.append(('dir', d))
        if self.priest_mode == 'cranky':
            self._show('"Talk?  Here is what I have to say!"')
            list(gen)
            return
        self._show('The priest of Anhur asks you for a contribution for the temple.', more=True)
        k = next(gen)
        assert k == ' ', k
        self._show('How much will you offer?', text=True)
        typed = ''
        for c in gen:
            if c == '\r':
                break
            typed += c
        self.calls.append(('offer', typed))
        offer = min(int(typed), self.blstats.gold)
        self.blstats.gold -= offer
        xl = self.blstats.experience_level
        self._show(f'You give the priest of Anhur {offer} zorkmids.', more=True)
        if 400 * xl <= offer < 600 * xl:
            self.ublessed = self.ublessed + 1 if self.ublessed else 3
            self.blstats.armor_class = 8 - self.ublessed
            self._show('"Thou hast been rewarded for thy devotion."')
        elif offer >= 600 * xl:
            self._show('"Thy selfless generosity is deeply appreciated."')
        else:
            self._show('"Thou art indeed a pious individual."')
        self.blstats.time += 1


def mines(agent, n):
    agent.level = Lvl(Level.GNOMISH_MINES, n)


def put_priest(agent, y, x, peaceful=True, altar=(None, None)):
    agent.glyphs[y, x] = PRIEST
    agent.monster_tracker.peaceful_monster_mask[y, x] = peaceful
    ay, ax = altar if altar[0] is not None else (y, x + 1)
    agent.level.objects[ay, ax] = SS.S_altar


@contextlib.contextmanager
def cfg(**kw):
    old = {k: getattr(jf_config, k) for k in kw}
    for k, v in kw.items():
        setattr(jf_config, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(jf_config, k, v)


def test_rules():
    assert PB.price(1) == 400 and PB.price(3) == 1200 and PB.price(0) == 400
    assert PB.expected_donations(2000, 1) == 5 and PB.expected_donations(1599, 2) == 1
    assert PB.classify('"Thou hast been rewarded for thy devotion."') == 'rewarded'
    assert PB.classify('"Thy selfless generosity is deeply appreciated."') == 'capped'
    assert PB.classify('"Talk?  Here is what I have to say!"') == 'cranky'
    assert PB.classify('The priest doesn\'t want anything to do with you!') == 'cranky'
    assert PB.classify('"Cheapskate."') == 'too_small'
    assert PB.classify('The priest is not interested.') == 'no_gold'


def test_flag_off_and_eligibility():
    with cfg(BUY_PROTECTION=False):
        b = PB.ProtectionBuyer(FakeAgent())
        assert not b.trip_active() and not b.done
    with cfg(BUY_PROTECTION=True):
        a = FakeAgent(gold=1500)
        b = PB.ProtectionBuyer(a)
        assert b.trip_active() and b.started == 1 and b.target_level() == (Level.GNOMISH_MINES, 3)
        assert any('PROT trip: off' in m for m in a.logs)
        b = PB.ProtectionBuyer(FakeAgent(role=Character.VALKYRIE))
        assert not b.trip_active() and b.done and b.reason == 'role'
        b = PB.ProtectionBuyer(FakeAgent(role=Character.TOURIST, gold=300))
        assert not b.trip_active() and b.done
        b = PB.ProtectionBuyer(FakeAgent(xl=4, gold=2000))
        assert not b.trip_active() and b.done
        a = FakeAgent()
        a.character.role = None
        b = PB.ProtectionBuyer(a)
        assert not b.trip_active() and not b.done      # waits for the role
        with cfg(BUY_PROT_ROLES=None):
            assert PB.ProtectionBuyer(FakeAgent(role=Character.VALKYRIE)).trip_active()


def test_aborts():
    with cfg(BUY_PROTECTION=True, BUY_PROT_TURNS=5000):
        a = FakeAgent()
        b = PB.ProtectionBuyer(a)
        assert b.trip_active()
        a.blstats.time = 6000
        assert not b.trip_active() and b.reason == 'out of time'
        a = FakeAgent()
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        a.blstats.hitpoints = 3
        assert not b.trip_active() and b.reason.startswith('low HP')
        a = FakeAgent()
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        a.blstats.experience_level = 4        # 1600 > 1500 gold: nothing left to buy
        assert not b.trip_active() and b.reason.startswith('gold')
        a = FakeAgent()
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        a.prayer_failed = True
        assert not b.trip_active() and b.reason == 'prayer failed'


def test_town_search():
    with cfg(BUY_PROTECTION=True, BUY_PROT_LEVEL_TURNS=400):
        a = FakeAgent()
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        mines(a, 3)
        for t in range(100, 700, 100):
            a.blstats.time = t
            b.update()
        assert 3 in b.not_town and b.target_level() == (Level.GNOMISH_MINES, 4)
        mines(a, 4)
        a.level.objects[5, 5] = SS.S_altar
        b.update()
        assert b.town == (Level.GNOMISH_MINES, 4) and b.target_level() == b.town
        # no town on either level ends the trip
        a = FakeAgent()
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        b.not_town.update({3, 4})
        assert not b.trip_active() and b.reason.startswith('no Minetown')
        # a shopkeeper seen by global_logic marks the town too
        a = FakeAgent()
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        mines(a, 3)
        a.global_logic.minetown_level = (Level.GNOMISH_MINES, 3)
        b.update()
        assert b.town == (Level.GNOMISH_MINES, 3)


def test_magic_map_rules_out():
    with cfg(BUY_PROTECTION=True):
        a = FakeAgent(role=Character.TOURIST, gold=900)
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        mines(a, 3)
        b._map_scroll = lambda: object()
        assert b.map_strategy().run(return_condition=True)
        assert a.global_logic.dive.reads == 1
        assert not b.map_strategy().check_condition()       # once per level
        a.blstats.time += 3
        b.update()
        assert 3 in b.not_town


def test_donations_until_gold_runs_out():
    with cfg(BUY_PROTECTION=True):
        a = FakeAgent(gold=2000)
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        mines(a, 3)
        put_priest(a, 10, 41)
        b.update()
        assert b.town is not None and b.priest_seen
        for _ in range(10):
            if not b.donate_strategy().run(return_condition=True):
                break
        offers = [c[1] for c in a.calls if c[0] == 'offer']
        assert offers == ['400'] * 5, offers
        assert ('dir', A.CompassDirection.E) in a.calls
        assert b.donations == 5 and a.blstats.gold == 0 and a.blstats.armor_class == 1
        assert not b.trip_active() and b.reason == 'bought'


def test_offer_scales_with_xl():
    with cfg(BUY_PROTECTION=True):
        a = FakeAgent(gold=1700, xl=2)
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        mines(a, 4)
        put_priest(a, 9, 39)
        while b.donate_strategy().run(return_condition=True):
            pass
        assert [c[1] for c in a.calls if c[0] == 'offer'] == ['800', '800']
        assert ('dir', A.CompassDirection.NW) in a.calls and a.blstats.gold == 100


def test_no_chat_when_unsafe():
    with cfg(BUY_PROTECTION=True):
        a = FakeAgent()
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        mines(a, 3)
        put_priest(a, 10, 41, peaceful=False)
        assert not b.donate_strategy().check_condition()          # hostile priest
        a = FakeAgent()
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        mines(a, 3)
        put_priest(a, 10, 41, altar=(2, 70))
        assert not b.donate_strategy().check_condition()          # no altar near him: not in his temple
        a = FakeAgent()
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        mines(a, 3)
        put_priest(a, 10, 41)
        a.blstats.hitpoints = 5
        assert not b.donate_strategy().check_condition()          # hurt: rest first
        a.blstats.hitpoints = 12
        a.hostiles = [(1, 10, 39, None, 0)]
        assert not b.donate_strategy().check_condition()          # fight first
        a.hostiles = []
        a.character.prop.hallu = True
        assert not b.donate_strategy().check_condition()
        a.character.prop.hallu = False
        assert b.donate_strategy().check_condition()
    with cfg(BUY_PROTECTION=False):
        assert not b.donate_strategy().check_condition()


def test_walks_to_priest():
    with cfg(BUY_PROTECTION=True, BUY_PROT_WALK_STEPS=8):
        a = FakeAgent()
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        mines(a, 3)
        put_priest(a, 10, 45)
        assert b.donate_strategy().run(return_condition=True)
        go = [c for c in a.calls if c[0] == 'go_to']
        assert go and max(abs(go[0][1] - 10), abs(go[0][2] - 45)) == 1 and go[0][3] == 8
        assert not any(c[0] == 'chat' for c in a.calls)


def test_cranky_priest_stops():
    with cfg(BUY_PROTECTION=True):
        a = FakeAgent()
        a.priest_mode = 'cranky'
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        mines(a, 3)
        put_priest(a, 10, 41)
        b.donate_strategy().run()
        assert b.stop_buying and b.reason == 'cranky'
        assert not b.donate_strategy().check_condition()
        assert not b.trip_active()


def test_orcish_town():
    class Orc:
        mlet = PB.S_ORC

    with cfg(BUY_PROTECTION=True, BUY_PROT_ORC_TOWN_HOSTILES=3):
        a = FakeAgent()
        b = PB.ProtectionBuyer(a)
        b.trip_active()
        mines(a, 3)
        a.level.objects[5, 5] = SS.S_altar
        b.update()
        assert b.town is not None and not b.done
        a.hostiles = [(4, 5, 5 + i, Orc(), HILL_ORC) for i in range(3)]
        b.update()
        assert b.done and 'Orcish' in b.reason


def test_not_during_trip_when_anytime_off():
    with cfg(BUY_PROTECTION=True, BUY_PROT_ANYTIME=False):
        a = FakeAgent(xl=1, gold=500)
        b = PB.ProtectionBuyer(a)
        mines(a, 3)
        put_priest(a, 10, 41)
        assert not b.donate_strategy().check_condition()     # trip never started
        with cfg(BUY_PROT_ANYTIME=True):
            assert b.donate_strategy().check_condition()


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print('ok', t.__name__)
    print(f'{len(tests)} passed')
