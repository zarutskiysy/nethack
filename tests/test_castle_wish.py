"""Unit tests (fakes, no NetHack) for CASTLE_WISH_FIRST and the castle_treasury fixes (research/castle_wish.md).
Run from the repo root:  python tests/test_castle_wish.py"""
import contextlib
import os
import sys

import nle.nethack as nh
import numpy as np

sys.path.insert(0, os.getcwd())

from nhbot import jf_config                                   # noqa: E402
from nhbot import objects as O                                # noqa: E402
from nhbot import castle_cross                                # noqa: E402
from nhbot import castle_treasury as ct                       # noqa: E402
from nhbot.castle_logic import to_bot                         # noqa: E402
from nhbot.exceptions import AgentPanic                       # noqa: E402
from nhbot.glyph import SS                                    # noqa: E402
from nle.nethack import actions as A                          # noqa: E402

H, W = 21, 79
CASTLE_KEY = (0, 27)


class Perm:
    def __init__(self, name):
        self.mname = name


class BL:
    def __init__(self, pos, hp=30, maxhp=30, time=10000):
        self.y, self.x = (int(v) for v in to_bot(*pos))
        self.hitpoints, self.max_hitpoints, self.time = hp, maxhp, time


class FakeItem:
    CURSED, UNCURSED = 'cursed', 'uncursed'

    def __init__(self, name, letter, category=nh.WEAPON_CLASS, equipped=False, status='uncursed'):
        self.text = f'a {name}'
        self.letter = letter
        self.category = category
        self.equipped = equipped
        self.status = status
        obj = O.from_name(name)
        self.objs = [obj]
        self.object = obj
        self.glyphs = [0]

    def is_unambiguous(self):
        return True


class Items(list):
    main_hand = None

    def get_letter(self, item):
        return item.letter

    def update(self, force=False):
        pass

    def free_slots(self):
        return 10


class Inv:
    def __init__(self):
        self.items = Items()
        self.items_below_me = []


class Prop:
    blind = polymorph = False


class Char:
    prop = Prop()


class Lvl:
    def key(self):
        return CASTLE_KEY


class FakeAgent:
    def __init__(self, pos, hp=30, maxhp=30, wallwalk=True):
        self.blstats = BL(pos, hp, maxhp)
        self.step_count = 1000
        self.glyphs = np.full((H, W), SS.S_stone, dtype=np.int32)
        self.inventory = Inv()
        self.character = Char()
        self.monsters = []          # (dist, y, x, Perm, glyph)
        self.logs = []
        self.moves = []
        self.steps = []
        self.message = ''
        self.single_message = ''
        self.move_ok = True

    def current_level(self):
        return Lvl()

    def log(self, msg):
        self.logs.append(msg)

    def get_visible_monsters(self):
        return list(self.monsters)

    @contextlib.contextmanager
    def atom_operation(self):
        yield

    def step(self, cmd, gen=None):
        self.steps.append(cmd)
        self.step_count += 1

    def type_text(self, text):
        self.steps.append(('text', text))

    def search(self, n=1):
        self.steps.append('search')
        self.step_count += 1

    def calc_direction(self, y0, x0, y1, x1):
        dy, dx = int(np.sign(y1 - y0)), int(np.sign(x1 - x0))
        return {(-1, 0): 'n', (1, 0): 's', (0, 1): 'e', (0, -1): 'w', (-1, 1): 'ne', (-1, -1): 'nw',
                (1, 1): 'se', (1, -1): 'sw'}[(dy, dx)]

    def direction(self, d):
        self.moves.append(d)
        self.step_count += 1
        if self.move_ok:
            dy, dx = {v: k for k, v in ct._DIR.items()}[d]
            self.blstats.y += dy
            self.blstats.x += dx

    def kick(self, y, x):
        self.steps.append(('kick', y, x))


class FakeCastle:
    def __init__(self, agent):
        self.agent = agent
        self.castle_key = CASTLE_KEY
        self.dive = None

    def _pos(self):
        from nhbot.castle_logic import to_map
        return to_map(self.agent.blstats.y, self.agent.blstats.x)

    def _monster_at(self, mx, my):
        y, x = to_bot(mx, my)
        return any((m[1], m[2]) == (y, x) for m in self.agent.monsters)


def flags(**kw):
    for k, v in kw.items():
        setattr(jf_config, k, v)


@contextlib.contextmanager
def patched(obj, **kw):
    old = {k: getattr(obj, k) for k in kw}
    for k, v in kw.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


def set_glyph(agent, p, g):
    y, x = to_bot(*p)
    agent.glyphs[y, x] = g


def soldier_at(agent, p):
    y, x = to_bot(*p)
    agent.monsters.append((1, y, x, Perm('soldier'), nh.GLYPH_MON_OFF + 1))


OBJ_GLYPH = nh.GLYPH_OBJ_OFF + 300   # any object glyph (a scroll on top of the chest)


# ---------------------------------------------------------------- flags and tower knowledge
def test_flag_default_off():
    assert jf_config.CASTLE_WISH_FIRST is False
    assert ct._search() == ct.SEARCH and ct._max_towers() == 1
    flags(CASTLE_WISH_FIRST=True)
    assert set(ct._search()) == {(4, 2), (58, 2), (4, 14), (58, 14)} and ct._max_towers() == 4


def test_tower_status():
    agent = FakeAgent((30, -2))
    castle = FakeCastle(agent)
    assert ct.tower_status(castle, (4, 2)) is None                 # never seen
    set_glyph(agent, (4, 2), SS.S_room)
    assert ct.tower_status(castle, (4, 2)) == 'floor'
    set_glyph(agent, (58, 2), OBJ_GLYPH)
    assert ct.tower_status(castle, (58, 2)) == 'object'
    soldier_at(agent, (4, 14))
    assert ct.tower_status(castle, (4, 14)) == 'soldier'
    agent.monsters = [(1, *to_bot(4, 14), Perm('ki-rin'), nh.GLYPH_MON_OFF + 2)]
    assert ct.tower_status(castle, (4, 14)) is None                # not a soldier: proves nothing


def test_note_towers():
    flags(CASTLE_WISH_FIRST=True)
    agent = FakeAgent((30, -2))
    castle = FakeCastle(agent)
    state = ct.TreasuryState(0, 0)
    set_glyph(agent, (4, 2), SS.S_room)
    set_glyph(agent, (58, 14), OBJ_GLYPH)
    soldier_at(agent, (58, 2))
    seen = ct._note_towers(castle, state)
    assert seen == {(58, 14)}
    assert state.visited == {(4, 2), (58, 2)}


# ---------------------------------------------------------------- the xorn walk
def _run_step(agent, path_fn):
    castle = FakeCastle(agent)
    with patched(castle_cross, wallwalker=lambda a: True, _xorn_path=path_fn):
        r = ct.step(castle)
    return castle, r


def test_goal_prefers_object_tower():
    flags(CASTLE_WISH_FIRST=True)
    agent = FakeAgent((30, -2))
    set_glyph(agent, (58, 14), OBJ_GLYPH)
    seen = {}

    def path(castle, start, goals=None, blocked=(), moat_cost=20, moat_side_cost=4):
        seen['goals'] = set(goals)
        return [start, (31, -2), (58, 14)]

    castle, r = _run_step(agent, path)
    assert r is True and seen['goals'] == {(58, 14)} and agent.moves == ['e']


def test_flag_off_keeps_east_search():
    agent = FakeAgent((30, -2))
    seen = {}

    def path(castle, start, goals=None, blocked=(), moat_cost=20, moat_side_cost=4):
        seen['goals'] = set(goals)
        return [start, (31, -2), (58, 2)]

    _run_step(agent, path)
    assert seen['goals'] == {(58, 2), (58, 14)}


def test_monster_on_the_way():
    def path(castle, start, goals=None, blocked=(), moat_cost=20, moat_side_cost=4):
        return [start, (31, -1), (58, 2)]

    # flag off: the detour ends
    agent = FakeAgent((30, -2))
    soldier_at(agent, (31, -1))
    castle, r = _run_step(agent, path)
    assert r is False and castle._treasury.done and 'monster on the way' in castle._treasury.reason
    # flag on: we hit it (F + direction)
    flags(CASTLE_WISH_FIRST=True)
    agent = FakeAgent((30, -2))
    soldier_at(agent, (31, -1))
    castle, r = _run_step(agent, path)
    assert r is True and not castle._treasury.done
    assert A.Command.FIGHT in agent.steps and agent.moves == ['se']


def test_soldier_on_chest_square_rules_tower_out():
    flags(CASTLE_WISH_FIRST=True)

    def path(castle, start, goals=None, blocked=(), moat_cost=20, moat_side_cost=4):
        return [start, (58, 2)]

    agent = FakeAgent((57, 1))
    soldier_at(agent, (58, 2))
    castle, r = _run_step(agent, path)
    assert r is True and (58, 2) in castle._treasury.visited and A.Command.FIGHT not in agent.steps


def test_sea_monster_is_routed_around():
    flags(CASTLE_WISH_FIRST=True)
    agent = FakeAgent((30, -2))
    y, x = to_bot(5, 0)    # a shark in the moat ring (castle.des (05,00))
    agent.monsters.append((3, y, x, Perm('shark'), nh.GLYPH_MON_OFF + 3))
    seen = {}

    def path(castle, start, goals=None, blocked=(), moat_cost=20, moat_side_cost=4):
        seen['blocked'] = set(blocked)
        return [start, (29, -2)]

    _run_step(agent, path)
    assert (5, 0) in seen['blocked'] and (40, 8) in seen['blocked']


# ---------------------------------------------------------------- HP and the wand in the pack
def test_wand_named_before_hp_check():
    for on in (False, True):
        flags(CASTLE_WISH_FIRST=on)
        agent = FakeAgent((58, 2), hp=1, maxhp=30)
        castle = FakeCastle(agent)
        castle._treasury = ct.TreasuryState(0, 0)
        castle._treasury.acquired = True
        called = []
        with patched(ct, _identify_acquired=lambda c, s: called.append(1) or True), \
                patched(castle_cross, wallwalker=lambda a: True):
            r = ct.step(castle)
        assert r is True and called == [1], on


def test_refuge_ignores_hp():
    def path(castle, start, **kw):
        raise AssertionError('no walk on the chest square')

    called = []
    for on in (False, True):
        flags(CASTLE_WISH_FIRST=on)
        agent = FakeAgent((58, 2), hp=3, maxhp=30)
        castle = FakeCastle(agent)
        with patched(ct, _inspect=lambda c, s: called.append(on) or True), \
                patched(castle_cross, wallwalker=lambda a: True, _xorn_path=path):
            r = ct.step(castle)
        if on:
            assert r is True and called == [True]
        else:
            assert r is False and 'HP' in castle._treasury.reason


def test_low_hp_off_refuge_still_ends():
    flags(CASTLE_WISH_FIRST=True)
    agent = FakeAgent((30, -2), hp=4, maxhp=30)
    castle, r = _run_step(agent, lambda *a, **k: [a[1], (31, -2)])
    assert r is False and 'HP' in castle._treasury.reason


# ---------------------------------------------------------------- the lock
def _open_with(on, items, wielded=None):
    flags(CASTLE_WISH_FIRST=on)
    agent = FakeAgent((58, 2))
    for it in items:
        agent.inventory.items.append(it)
    agent.inventory.items.main_hand = wielded
    castle = FakeCastle(agent)
    state = ct.TreasuryState(0, 0)
    calls = []
    with patched(ct, _wield=lambda c, s, it: calls.append(('wield', it.object.name)) or True,
                 _kick=lambda c, s, p: calls.append(('kick', tuple(p))) or True):
        ct._open(castle, state, None)
    return calls, agent


def test_open_wields_pick_before_kicking():
    pick = FakeItem('pick-axe', 'x', category=nh.TOOL_CLASS)
    calls, _ = _open_with(False, [pick])
    assert calls == [('kick', (58, 2))]
    calls, _ = _open_with(True, [pick])
    assert calls == [('wield', 'pick-axe')]


def test_open_blade_first_and_force_with_wielded():
    pick = FakeItem('pick-axe', 'x', category=nh.TOOL_CLASS, equipped=True)
    sword = FakeItem('long sword', 'a')
    calls, _ = _open_with(True, [pick, sword], wielded=pick)
    assert calls == [('wield', 'long sword')]
    # the wielded pick-axe itself #forces when nothing better is carried
    calls, agent = _open_with(True, [pick], wielded=pick)
    assert calls == [] and A.Command.FORCE in agent.steps


def test_key_first_then_force():
    key = FakeItem('skeleton key', 'k', category=nh.TOOL_CLASS)
    pick = FakeItem('pick-axe', 'x', category=nh.TOOL_CLASS, equipped=True)
    for on in (False, True):
        flags(CASTLE_WISH_FIRST=on)
        agent = FakeAgent((58, 2))
        agent.inventory.items.extend([key, pick])
        agent.inventory.items.main_hand = pick
        castle = FakeCastle(agent)
        state = ct.TreasuryState(0, 0)
        ct._open(castle, state, None)
        assert agent.steps[-1] == A.Command.APPLY
        state.open_tries[(58, 2)] = ct.WISH_MAX_UNLOCK_TRIES
        ct._open(castle, state, None)
        assert agent.steps[-1] == (A.Command.FORCE if on else A.Command.APPLY), on


def test_kick_square_order():
    flags(CASTLE_WISH_FIRST=True)
    agent = FakeAgent((58, 2))
    castle = FakeCastle(agent)
    state = ct.TreasuryState(0, 0)
    ct._kick(castle, state, (58, 2))
    # the first square tried is the tower's own floor, not the moat-side wall row 1
    first = agent.moves[0]
    assert first in ('s', 'e', 'w', 'se', 'sw'), first
    assert state.kick_target == (58, 2)
    assert ct._kick_square_rank((58, 1)) > ct._kick_square_rank((57, 3))


# ---------------------------------------------------------------- on foot
def test_foot_waypoints():
    assert ct.foot_waypoints((59, 3), (58, 2)) == [(58, 2)]
    assert ct.foot_waypoints((59, 3), (4, 2)) == [(56, 3), (55, 3), (54, 3), (8, 3), (7, 3), (6, 3), (4, 2)]
    assert ct.foot_waypoints((55, 3), (4, 2)) == [(54, 3), (8, 3), (7, 3), (6, 3), (4, 2)]
    assert ct.foot_waypoints((30, 3), (4, 2)) == [(8, 3), (7, 3), (6, 3), (4, 2)]
    assert ct.foot_waypoints((5, 13), (58, 14)) == [(6, 13), (7, 13), (8, 13), (54, 13), (55, 13), (56, 13),
                                                    (58, 14)]
    assert ct.foot_waypoints((59, 3), (58, 14)) is None             # the other hallway: not on foot
    assert ct.foot_waypoints((30, 8), (58, 2)) is None


class Front:
    phase = 'wand'
    done = False


class Dive:
    front = None


def test_foot_ready():
    agent = FakeAgent((59, 3))
    castle = FakeCastle(agent)
    castle.dive = Dive()
    castle._treasury = ct.TreasuryState(0, 0)
    with patched(castle_cross, wallwalker=lambda a: False):
        assert not ct._foot_ready(castle)                          # flag off
        flags(CASTLE_WISH_FIRST=True)
        assert ct._foot_ready(castle)
        castle.dive.front = Front()
        assert not ct._foot_ready(castle)                          # FRONT_V3's own tower walk
        castle.dive.front = None
        agent.blstats = BL((30, 8))
        assert not ct._foot_ready(castle)                          # the throne room: not ours
        castle._treasury.done = True
        agent.blstats = BL((59, 3))
        assert not ct._foot_ready(castle)
    with patched(castle_cross, wallwalker=lambda a: True):
        castle._treasury.done = False
        assert not ct._foot_ready(castle)                          # the xorn walk has it


def test_form_loss_keeps_state_with_flag():
    for on in (False, True):
        flags(CASTLE_WISH_FIRST=on)
        agent = FakeAgent((59, 3))
        castle = FakeCastle(agent)
        castle._treasury = ct.TreasuryState(0, 0)
        with patched(castle_cross, wallwalker=lambda a: False):
            assert ct.step(castle) is False
        assert castle._treasury.done is (not on)


def test_foot_step_walks_to_own_chest_then_inspects():
    flags(CASTLE_WISH_FIRST=True)
    agent = FakeAgent((56, 3))
    castle = FakeCastle(agent)
    castle._treasury = ct.TreasuryState(0, 0)
    set_glyph(agent, (58, 2), OBJ_GLYPH)
    inspected = []
    with patched(castle_cross, wallwalker=lambda a: False), \
            patched(ct, _inspect=lambda c, s: inspected.append(tuple(int(v) for v in c._pos())) or True):
        assert ct._foot_step(castle) is True
        assert agent.moves == ['ne'] and tuple(int(v) for v in castle._pos()) == (57, 2)
        assert ct._foot_step(castle) is True
        assert tuple(int(v) for v in castle._pos()) == (58, 2)
        assert ct._foot_step(castle) is True
    assert inspected == [(58, 2)]


def test_foot_step_empty_tower_goes_to_partner():
    flags(CASTLE_WISH_FIRST=True)
    agent = FakeAgent((56, 3))
    castle = FakeCastle(agent)
    castle._treasury = ct.TreasuryState(0, 0)
    set_glyph(agent, (58, 2), SS.S_room)                           # seen bare: the wand is elsewhere
    with patched(castle_cross, wallwalker=lambda a: False):
        assert ct._foot_step(castle) is True
    assert (58, 2) in castle._treasury.visited
    assert castle._treasury.foot_target == (4, 2) and agent.moves == ['w']   # out by the door (55,3)


def test_foot_step_nothing_in_reach():
    flags(CASTLE_WISH_FIRST=True)
    agent = FakeAgent((56, 3))
    castle = FakeCastle(agent)
    castle._treasury = ct.TreasuryState(0, 0)
    castle._treasury.visited |= {(58, 2), (4, 2)}
    with patched(castle_cross, wallwalker=lambda a: False):
        assert ct._foot_step(castle) is False
    assert castle._treasury.done and 'no unchecked tower' in castle._treasury.reason


def test_panic_in_foot_step_finishes():
    flags(CASTLE_WISH_FIRST=True)
    agent = FakeAgent((58, 2))
    castle = FakeCastle(agent)
    castle._treasury = ct.TreasuryState(0, 0)

    def boom(c, s):
        raise AgentPanic('several containers here')

    with patched(ct, _inspect=boom):
        try:
            ct._foot_step(castle)
            assert 0
        except AgentPanic:
            pass
    assert castle._treasury.done


if __name__ == '__main__':
    default = jf_config.CASTLE_WISH_FIRST
    assert default is False
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            flags(CASTLE_WISH_FIRST=default)
            n += 1
            print('ok', name)
    print(f'{n} tests passed')
