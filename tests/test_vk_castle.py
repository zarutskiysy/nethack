"""Unit tests (fakes, no NetHack game) for the vk_castle port of vkurenkov s26 4921bc3's castle modules:
passtune.py, castle_crusher.py (PASSTUNE_CRUSHER), castle_inner.py (CASTLE_INNER, LIFT_EAST_DROP), the landing lane
(LANDING_CRUSH_FIRST / LANDING_DIRECT / LANDING_FOCUS / LANDING_ROUTE), CASTLE_ZAP_RECOGNIZE, INV_FULL_LIST,
tele_route's T_ROUTE_FIRE helpers and WISH_PRAYER_HOLD. vk ships no tests in its repo; these check the ported
mechanics and, above all, that every master switch is OFF by default and inert when off.
Run from the repo root:  python tests/test_vk_castle.py"""
import contextlib
import os
import sys
import types

import numpy as np

sys.path.insert(0, os.getcwd())

from nhbot import jf_config                                   # noqa: E402
from nhbot import passtune                                    # noqa: E402
from nhbot import castle_cross                                # noqa: E402
from nhbot import castle_inner                                # noqa: E402
from nhbot import tele_route                                  # noqa: E402
from nhbot.castle_crusher import Crusher                      # noqa: E402
from nhbot.castle_inner import CastleInner                    # noqa: E402
from nhbot.castle_logic import CastlePassage                  # noqa: E402
from nhbot.dive_logic import DiveLogic                        # noqa: E402
from nhbot.item.inventory_items import InventoryItems         # noqa: E402
from nhbot.level import Level                                 # noqa: E402


@contextlib.contextmanager
def flags(**kw):
    old = {k: getattr(jf_config, k) for k in kw}
    for k, v in kw.items():
        setattr(jf_config, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(jf_config, k, v)


MASTERS = ['PASSTUNE_CRUSHER', 'CASTLE_INNER', 'LANDING_CRUSH_FIRST', 'LANDING_DIRECT', 'LANDING_ROUTE',
           'LANDING_FOCUS', 'LIFT_EAST_DROP', 'EAST_LATE_DOOR', 'POLY_RESUME', 'WISH_ROUTE_FIRST', 'PREEMPT_SAFE',
           'CASTLE_ZAP_RECOGNIZE', 'XORN_STAIRS_NOTE', 'INV_FULL_LIST', 'MATTOCK_SHIELD', 'T_ROUTE_FIRE',
           'T_ROUTE_EARLY_CHARGE', 'T_ROUTE_TOP', 'ROUTE_ELBERETH', 'WISH_PRAYER_HOLD', 'ROUTE_RING_SWAP',
           'T_BLIND_READ', 'LANDING_QUIET_TESTS', 'LANDING_DIRECT_ANY', 'LANDING_ROUTE_ALL', 'LANDING_ROUTE_ZAP']


def test_every_ported_master_switch_is_off_by_default():
    for name in MASTERS:
        assert getattr(jf_config, name) is False, name


# ---------------------------------------------------------------- passtune (music.c Mastermind)
def test_feedback_counts_like_music_c():
    # gears = right note right place, tumblers = right note wrong place, each tune note used once
    fb = passtune.feedback(passtune.to_code('ABCDE'), np.array([passtune.to_code('ABCDE'),
                                                                 passtune.to_code('EDCBA'),
                                                                 passtune.to_code('GGGGG'),
                                                                 passtune.to_code('AAAAB')]))
    assert list(fb) == [5 * 6 + 0, 1 * 6 + 4, 0, 1 * 6 + 1]


def test_parse_feedback_messages():
    assert passtune.parse_feedback('You hear 2 tumblers click and 1 gear turn.') == (1, 2)
    assert passtune.parse_feedback('You hear 3 gears turn.') == (3, 0)
    assert passtune.parse_feedback('You hear 1 tumbler click.') == (0, 1)
    assert passtune.parse_feedback('You produce a lilting melody.') is None


def test_solver_finds_random_tunes_in_few_plays():
    rng = np.random.default_rng(7)
    codes = passtune._codes()
    worst = 0
    for i in rng.choice(len(codes), 25, replace=False):
        secret = codes[i]
        s = passtune.Solver()
        for plays in range(1, 12):
            g = s.next_guess()
            fb = int(passtune.feedback(passtune.to_code(g), secret[None, :])[0])
            if fb == 30:
                break
            assert s.update(g, fb // 6, fb % 6) > 0
        worst = max(worst, plays)
    assert worst <= 8, worst


# ---------------------------------------------------------------- fakes for the castle classes
def fake_dive(pos_map=(10, 8), castle_key=None, instrument=None, levitating=False):
    agent = types.SimpleNamespace()
    agent.blstats = types.SimpleNamespace(y=pos_map[1] + 3, x=pos_map[0] + 8, time=1000, depth=27, hitpoints=50,
                                          max_hitpoints=60, dungeon_number=0, level_number=27)
    agent.log = lambda *a, **k: None
    agent.character = types.SimpleNamespace(prop=types.SimpleNamespace(polymorph=False))
    agent.inventory = types.SimpleNamespace(items=[instrument] if instrument else [])
    level = types.SimpleNamespace(key=lambda: (0, 27), dungeon_number=0)
    agent.current_level = lambda: level
    dive = types.SimpleNamespace(agent=agent)
    dive.castle = types.SimpleNamespace(castle_key=castle_key, levitating=lambda: levitating,
                                        water_walking=lambda: False, _floating=lambda: levitating,
                                        committed=lambda: True)
    return dive


def test_crusher_and_inner_inert_with_flags_off():
    dive = fake_dive()
    c = Crusher(dive)
    dive.crusher = c
    inner = CastleInner(dive)
    dive.inner = inner
    # flags off: nothing looks further than the switch (no castle, no inventory needed)
    assert c.active() is False and c.approach_step() is False
    assert inner.active() is False and inner.takes_over() is False
    assert castle_cross.crusher_first(dive) is False
    # the strategies yield False at once (no game step)
    assert castle_inner.strategy(dive).check_condition() is False
    from nhbot import castle_crusher
    assert castle_crusher.strategy(dive).check_condition() is False


def test_crusher_first_needs_both_switches():
    dive = fake_dive()
    c = Crusher(dive)
    dive.crusher = c
    c._instrument = lambda: object()
    with flags(LANDING_CRUSH_FIRST=True):
        assert castle_cross.crusher_first(dive) is False      # PASSTUNE_CRUSHER still off
    with flags(LANDING_CRUSH_FIRST=True, PASSTUNE_CRUSHER=True):
        assert castle_cross.crusher_first(dive) is True
        c.tune = 'ABCDE'
        assert castle_cross.crusher_first(dive) is False      # the tune is known: tests may resume


def test_lift_east_drop_yields_over_the_east_trap_door():
    dive = fake_dive(pos_map=(55, 8), levitating=True)
    dive.crusher = None
    inner = CastleInner(dive)
    assert inner.owned_elsewhere() is False                   # flag off: castle_inner would take the hovering hero
    with flags(LIFT_EAST_DROP=True):
        assert inner.owned_elsewhere() is True
    dive2 = fake_dive(pos_map=(54, 8), levitating=True)
    dive2.crusher = None
    with flags(LIFT_EAST_DROP=True):
        assert CastleInner(dive2).owned_elsewhere() is False  # only on (55,8)


def test_inside_shell_geometry():
    assert castle_inner.inside((10, 8))       # antechamber
    assert castle_inner.inside((30, 8))       # throne room
    assert not castle_inner.inside((2, 8))    # west courtyard
    assert not castle_inner.inside((-3, 8))   # west maze


# ---------------------------------------------------------------- dive_logic hooks
class FakeDiveSelf:
    _zap_down_castle_check = DiveLogic._zap_down_castle_check
    landing_pending = DiveLogic.landing_pending

    def __init__(self, msgs, depth=27, castle_key=None):
        lvl = types.SimpleNamespace(key=lambda: (0, 27), dungeon_number=Level.DUNGEONS_OF_DOOM)
        self.agent = types.SimpleNamespace(
            current_level=lambda: lvl, blstats=types.SimpleNamespace(depth=depth, armor_class=3),
            _message_history=list(msgs[:-1]), message=msgs[-1], log=lambda *a, **k: None,
            inventory=types.SimpleNamespace(items=types.SimpleNamespace(all_items=[], get_letter=lambda i: 'a')))
        self.undiggable = set()
        self.bottomed = []
        self.castle = types.SimpleNamespace(castle_key=castle_key, on_bottom=self.bottomed.append)


def test_zap_recognize_off_does_nothing():
    d = FakeDiveSelf(['You dig a pit in the floor.'])
    d._zap_down_castle_check((0, 27))
    assert d.bottomed == [] and d.undiggable == set()


def test_zap_recognize_pit_or_hard_floor_is_the_castle():
    with flags(CASTLE_ZAP_RECOGNIZE=True):
        # the pit message on an earlier page (a monster's attack replaced the last one)
        d = FakeDiveSelf(['You dig a pit in the floor.', 'The minotaur hits!'])
        d._zap_down_castle_check((0, 27))
        assert d.bottomed == [(0, 27)] and (0, 27) in d.undiggable
        d = FakeDiveSelf(['The floor here is too hard to dig in.'])
        d._zap_down_castle_check((0, 27))
        assert d.bottomed == [(0, 27)]
        d = FakeDiveSelf(['You dig a pit in the floor.'], depth=20)    # above castle depth: not the castle
        d._zap_down_castle_check((0, 27))
        assert d.bottomed == []
        d = FakeDiveSelf(['You dig a pit in the floor.'], castle_key=(0, 27))   # already known
        d._zap_down_castle_check((0, 27))
        assert d.bottomed == []


def test_landing_pending_needs_focus_and_crusher():
    d = FakeDiveSelf(['x'])
    d.crusher = types.SimpleNamespace(done=False, destroyed=False, tune=None, logged=set(), on_castle=lambda: True,
                                      _instrument=lambda: object())
    d.castle._floating = lambda: False
    d.agent.character = types.SimpleNamespace(prop=types.SimpleNamespace(polymorph=False))
    assert d.landing_pending() is False
    with flags(LANDING_FOCUS=True):
        assert d.landing_pending() is False
    with flags(LANDING_FOCUS=True, PASSTUNE_CRUSHER=True):
        assert d.landing_pending() is True
        d.crusher.logged.add('square')
        assert d.landing_pending() is False


# ---------------------------------------------------------------- LANDING_ROUTE's maze priors (castle_logic)
def test_route_classes_follow_the_west_maze():
    p = CastlePassage.__new__(CastlePassage)
    assert p._route_class(2, 3) == 'cell' and p._route_class(3, 3) == 'h'
    assert p._route_class(2, 4) == 'v' and p._route_class(3, 4) == 'corner'


# ---------------------------------------------------------------- INV_FULL_LIST (item/inventory_items.py)
class Boom(Exception):
    pass


def _fake_inventory(names):
    class It:
        def __init__(self, name):
            self.name, self.equipped = name, False

        def is_possible_container(self):
            return 'bag' in self.name

        def is_container(self):
            return False

        def weight(self):
            return 1

    strs = np.zeros((len(names), 80), np.uint8)
    for i, n in enumerate(names):
        strs[i, :len(n)] = list(n.encode())
    obs = {'inv_strs': strs, 'inv_oclasses': np.zeros(len(names), int),
           'inv_glyphs': np.full(len(names), 2000), 'inv_letters': np.array([ord('a') + i for i in range(len(names))])}
    calls = []

    def check(item):
        calls.append(item.name)
        raise Boom()
    agent = types.SimpleNamespace(last_observation=obs, log=lambda *a, **k: None, get_visible_monsters=lambda: [])
    agent.inventory = types.SimpleNamespace(
        item_manager=types.SimpleNamespace(get_item_from_text=lambda name, **k: It(name)),
        check_container_content=check)
    inv = InventoryItems.__new__(InventoryItems)
    inv.agent = agent
    inv._previous_inv_strs = None
    inv._clear()
    return inv, calls


def test_inv_full_list_off_cuts_the_list_at_the_bag():
    inv, _ = _fake_inventory(['a sword', 'an empty bag', 'a wand of wishing'])
    try:
        inv.update()
    except Boom:
        pass
    assert len(inv.all_items) == 2      # the old behaviour: everything after the bag is missing


def test_inv_full_list_on_finishes_the_list_then_raises():
    inv, calls = _fake_inventory(['a sword', 'an empty bag', 'a wand of wishing'])
    with flags(INV_FULL_LIST=True):
        raised = False
        try:
            inv.update()
        except Boom:
            raised = True
    assert raised and len(inv.all_items) == 3 and calls == ['an empty bag']


# ---------------------------------------------------------------- tele_route (T_ROUTE_FIRE) and WISH_PRAYER_HOLD
def _agent_with(prop):
    return types.SimpleNamespace(character=types.SimpleNamespace(prop=types.SimpleNamespace(**prop)))


def test_status_blocks_read_off_is_the_old_rule():
    base = dict(stun=False, confusion=False, blind=False, hallu=False)
    scroll = types.SimpleNamespace(text='2 cursed scrolls labeled FOO')
    for k in base:
        st = dict(base, **{k: True})
        assert tele_route._status_blocks_read(_agent_with(st), scroll) is True
    assert tele_route._status_blocks_read(_agent_with(base), scroll) is False
    with flags(T_ROUTE_FIRE=True):
        # level_tele() looks at neither blindness nor hallucination; a seen label can be read blind
        assert tele_route._status_blocks_read(_agent_with(dict(base, blind=True)), scroll) is False
        assert tele_route._status_blocks_read(_agent_with(dict(base, hallu=True)), scroll) is False
        assert tele_route._status_blocks_read(_agent_with(dict(base, blind=True)),
                                              types.SimpleNamespace(text='2 scrolls')) is True


def test_count_reads_the_stack_from_the_text_only_with_the_flag():
    it = types.SimpleNamespace(text='2 scrolls', count=1)
    assert tele_route._count(it) == 1
    with flags(T_ROUTE_FIRE=True):
        assert tele_route._count(it) == 2


def test_wish_prayer_hold_timeout():
    from nhbot import power
    from nhbot.agent import Agent
    a = types.SimpleNamespace(blstats=types.SimpleNamespace(time=100), step_count=0)
    a.wish_prayer_timeout = types.MethodType(Agent.wish_prayer_timeout, a)
    old = power.tele_route.note_asked
    power.tele_route.note_asked = lambda *x, **k: None
    try:
        with flags(WISH_LEARN=False):
            power.note_wish(a, 'blessed scroll of charging')
            assert a.wish_prayer_timeout() == 0                      # flag off: nothing recorded
            with flags(WISH_PRAYER_HOLD=True):
                power.note_wish(a, 'blessed scroll of charging')
                power.note_wish(a, 'ring of teleport control')
    finally:
        power.tele_route.note_asked = old
    assert a.wish_prayer_timeout() == 200
    a.blstats.time = 150
    assert a.wish_prayer_timeout() == 150


if __name__ == '__main__':
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} tests passed')
