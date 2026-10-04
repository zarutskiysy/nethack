"""Unit tests (fakes, no NetHack game) for castle_v2: the late-applied crusher-route bundle (CASTLE_V2), the peaceful
blocker fix (CASTLE_V2_PEACEFUL), the burned-Elbereth parse and burn step (CASTLE_V2_BURN) and the arrival census line
(CASTLE_CENSUS_LOG). Above all: every switch is off by default and the flag-off paths are the old ones.
Run from the repo root:  python tests/test_castle_v2.py"""
import contextlib
import json
import os
import sys
import types

import numpy as np

sys.path.insert(0, os.getcwd())

import nle.nethack as nh                                      # noqa: E402
from nle.nethack import actions as A                          # noqa: E402

from nhbot import castle_v2                                   # noqa: E402
from nhbot import jf_config                                   # noqa: E402
from nhbot import objects as O                                # noqa: E402
from nhbot.castle_logic import CastlePassage, to_bot          # noqa: E402
from nhbot.item.inventory import Inventory                    # noqa: E402

NHBOT = os.path.join(os.getcwd(), 'nhbot')


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


@contextlib.contextmanager
def bundle_guard():
    """Put the bundle's flags back after a test that applies it (the module only ever turns them on)."""
    old = {k: getattr(jf_config, k) for k in jf_config.CASTLE_V2_BUNDLE}
    castle_v2.new_game()
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(jf_config, k, v)
        castle_v2.new_game()


# ---------------------------------------------------------------- defaults and flag-off identity
def test_switches_off_by_default():
    assert jf_config.CASTLE_V2 is False
    assert jf_config.CASTLE_CENSUS_LOG is False
    # sub-switches only read under CASTLE_V2
    assert jf_config.CASTLE_V2_PEACEFUL is True and jf_config.CASTLE_V2_BURN is True
    assert castle_v2.active() is False


def test_bundle_names_exist_and_are_off_in_integ():
    assert len(jf_config.CASTLE_V2_BUNDLE) == 18
    for name in jf_config.CASTLE_V2_BUNDLE:
        assert hasattr(jf_config, name), name
        assert getattr(jf_config, name) is False, name
    # the early-acting vk flags stay out of the bundle (they act before the castle)
    for name in ('INV_FULL_LIST', 'PREEMPT_SAFE', 'MATTOCK_SHIELD'):
        assert name not in jf_config.CASTLE_V2_BUNDLE


def test_dive_logic_hook_is_gated():
    src = open(os.path.join(NHBOT, 'dive_logic.py')).read()
    assert 'if jf_config.CASTLE_V2 or jf_config.CASTLE_CENSUS_LOG:\n            # castle_v2' in src
    assert 'castle_v2.new_game()' in src
    src = open(os.path.join(NHBOT, 'castle_logic.py')).read()
    assert 'if jf_config.CASTLE_V2 and jf_config.CASTLE_V2_PEACEFUL and self._v2_peaceful_at(y, x):' in src
    src = open(os.path.join(NHBOT, 'castle_crusher.py')).read()
    assert 'castle_v2.burn_due(agent, self.tries[\'crush_burn\'])' in src


def test_apply_bundle_needs_the_switch_and_is_once_per_game():
    with bundle_guard():
        assert castle_v2.apply_bundle() is False                       # CASTLE_V2 off: nothing
        assert all(getattr(jf_config, n) is False for n in jf_config.CASTLE_V2_BUNDLE)
        logs = []
        agent = types.SimpleNamespace(log=logs.append)
        with flags(CASTLE_V2=True):
            assert castle_v2.apply_bundle(agent, 'test') is True
            assert all(getattr(jf_config, n) is True for n in jf_config.CASTLE_V2_BUNDLE)
            assert castle_v2.active()
            assert castle_v2.apply_bundle(agent, 'again') is False     # once per game
        assert len(logs) == 1 and logs[0].startswith('CASTLE_V2 bundle on (test): ')
        castle_v2.new_game()                                           # per-game state only
        assert castle_v2.active() is False
        assert all(getattr(jf_config, n) is True for n in jf_config.CASTLE_V2_BUNDLE)


# ---------------------------------------------------------------- the castle zone
def fake_dive(depth=26, dnum=0, level_number=None, medusa=(0, 24), castle_key=None, items=(), spells=None):
    level_number = depth if level_number is None else level_number
    logs = []
    agent = types.SimpleNamespace()
    agent.log = logs.append
    agent.blstats = types.SimpleNamespace(y=12, x=8, time=5000, depth=depth, hitpoints=50, max_hitpoints=60,
                                          experience_level=8, energy=30, max_energy=40, armor_class=2,
                                          dungeon_number=dnum, level_number=level_number)
    inv = types.SimpleNamespace(items=list(items), is_known_empty=lambda it: False)
    agent.inventory = inv
    agent.character = types.SimpleNamespace(known_spells=dict(spells or {}), role=None, name_to_role={})
    level = types.SimpleNamespace(key=lambda: (dnum, level_number), dungeon_number=dnum, level_number=level_number)
    agent.current_level = lambda: level
    dive = types.SimpleNamespace(agent=agent, medusa_level=medusa, _landing_direct={})
    dive.castle = types.SimpleNamespace(castle_key=castle_key)
    return dive, level, logs


def test_castle_zone():
    d, lv, _ = fake_dive(depth=24, medusa=(0, 21))
    assert not castle_v2.in_castle_zone(d, lv)                         # above 25: never the castle
    d, lv, _ = fake_dive(depth=26, medusa=(0, 24))
    assert castle_v2.in_castle_zone(d, lv)
    d, lv, _ = fake_dive(depth=26, medusa=None)
    assert castle_v2.in_castle_zone(d, lv)                             # Medusa skipped (trap door): as LANDING_DIRECT
    d, lv, _ = fake_dive(depth=24, medusa=None)
    assert not castle_v2.in_castle_zone(d, lv)
    d, lv, _ = fake_dive(depth=26, medusa=None, castle_key=(0, 26))
    assert castle_v2.in_castle_zone(d, lv)                             # ...or the castle recognised
    d, lv, _ = fake_dive(depth=25, medusa=(0, 25))
    assert not castle_v2.in_castle_zone(d, lv)                         # Medusa's own level (a 29-level Dungeons)
    d, lv, _ = fake_dive(depth=27, dnum=1, level_number=2, medusa=(0, 24))
    assert not castle_v2.in_castle_zone(d, lv)                         # Gehennom


def test_on_update_applies_bundle_in_zone_only():
    with bundle_guard():
        with flags(CASTLE_V2=True):
            d, lv, logs = fake_dive(depth=24, medusa=(0, 21))
            castle_v2.on_update(d, lv, lv.key())
            assert not castle_v2.active() and not logs
            d, lv, logs = fake_dive(depth=26, medusa=(0, 24))
            castle_v2.on_update(d, lv, lv.key())
            assert castle_v2.active() and logs and logs[0].startswith('CASTLE_V2 bundle on')


# ---------------------------------------------------------------- the census
def item(name, cls, count=1, text=None, unambiguous=True, cands=None, equipped=False, comment=''):
    objs = [types.SimpleNamespace(name=n) for n in (cands or [name])]
    it = types.SimpleNamespace(objs=objs, category=cls, count=count, text=text or name, equipped=equipped,
                               comment=comment)
    it.is_unambiguous = lambda: len(objs) == 1
    it.object = objs[0]
    return it


def test_wand_classes():
    assert castle_v2.wand_class(item('striking', nh.WAND_CLASS)) == 'striking'
    silent = item('x', nh.WAND_CLASS, cands=['secret door detection', 'create monster', 'nothing', 'undead turning',
                                             'opening', 'locking', 'probing'])
    assert castle_v2.wand_class(silent) == 'silent'
    assert castle_v2.wand_class(item('x', nh.WAND_CLASS, cands=['sleep', 'death'])) == 'sleep/death'
    assert castle_v2.wand_class(item('x', nh.WAND_CLASS, cands=['striking', 'fire', 'cold'])) == 'unknown'
    assert castle_v2.wand_class(item('digging', nh.WAND_CLASS, comment='EMPT'),
                                types.SimpleNamespace(is_known_empty=lambda i: False)) == 'empty'


def test_kit_routes_and_lane():
    horn = item('horn', nh.TOOL_CLASS, text='a horn', cands=['tooled horn', 'frost horn', 'fire horn', 'horn of plenty'])
    pick = item('pick-axe', nh.TOOL_CLASS)
    key = item('skeleton key', nh.TOOL_CLASS)
    silent = item('x', nh.WAND_CLASS, cands=['nothing', 'opening', 'locking', 'probing', 'undead turning'])
    earth = item('earth', nh.SCROLL_CLASS, count=2)
    d, lv, _ = fake_dive(items=[horn, pick, key, silent, earth], spells={'force bolt': 'a'})
    k = castle_v2.kit(d.agent)
    assert k['tonal'] == ['a horn'] and k['tonal_sure'] is False       # a horn of plenty is still possible
    assert k['dig_tool'] and k['unlock'] and k['wands'] == {'silent': 1} and k['scrolls'] == {'earth': 2}
    r = castle_v2.routes(d.agent, k)
    assert r['crusher'] and r['destroyer'] and r['destroy_fill'] and not r['opener_maybe'] and not r['wish']
    with flags(PASSTUNE_CRUSHER=False, CASTLE_PASSTUNE=False):
        assert castle_v2.lane(r) in ('lift', 'none', 'xorn')
    with flags(PASSTUNE_CRUSHER=True):
        assert castle_v2.lane(r) == 'crusher'
    # no instrument: the silent wand is a maybe-opener, nothing crushes
    d, lv, _ = fake_dive(items=[pick, silent])
    r = castle_v2.routes(d.agent, castle_v2.kit(d.agent))
    assert not r['crusher'] and r['opener_maybe'] and not r['destroyer']
    with flags(PASSTUNE_CRUSHER=True, CASTLE_PASSAGE=True):
        assert castle_v2.lane(r) == 'none'
    # opening + locking wands toggle the bridge too
    d, lv, _ = fake_dive(items=[item('opening', nh.WAND_CLASS), item('locking', nh.WAND_CLASS)])
    assert castle_v2.routes(d.agent, castle_v2.kit(d.agent))['crusher']


def test_census_line_once_per_castle_level():
    with bundle_guard():
        horn = item('tooled horn', nh.TOOL_CLASS, text='an uncursed tooled horn')
        d, lv, logs = fake_dive(items=[horn], castle_key=(0, 26), depth=26)
        castle_v2.on_update(d, lv, lv.key())
        assert not logs                                                # CASTLE_CENSUS_LOG off: silent
        with flags(CASTLE_CENSUS_LOG=True):
            castle_v2.on_update(d, lv, lv.key())
            castle_v2.on_update(d, lv, lv.key())
        assert len(logs) == 1 and logs[0].startswith('CASTLE_V2 census {')
        rec = json.loads(logs[0][len('CASTLE_V2 census '):])
        assert rec['depth'] == 26 and rec['level'] == [0, 26] and rec['pos'] == [0, 9]
        assert rec['kit']['tonal'] == ['an uncursed tooled horn'] and rec['kit']['tonal_sure'] is True
        assert rec['routes']['crusher'] is True and rec['v2_active'] is False
        assert set(rec['switches']) >= {'CASTLE_V2', 'PASSTUNE_CRUSHER', 'CASTLE_INNER'}
        # not the castle (yet): no line
        d, lv, logs = fake_dive(items=[horn], castle_key=None, depth=26)
        with flags(CASTLE_CENSUS_LOG=True):
            castle_v2.on_update(d, lv, lv.key())
        assert not logs


# ---------------------------------------------------------------- CASTLE_V2_PEACEFUL
class FakeAgent:
    def __init__(self, peaceful=False, pet=False):
        self.blstats = types.SimpleNamespace(y=12, x=7, time=100, depth=26)
        self.glyphs = np.full((21, 79), 2359, dtype=np.int32)          # S_stone-ish background
        self.monster_tracker = types.SimpleNamespace(monster_mask=np.zeros((21, 79), bool),
                                                     peaceful_monster_mask=np.zeros((21, 79), bool))
        y, x = to_bot(0, 9)                                            # the target square (map (0, 9))
        self.target = (y, x)
        self.glyphs[y, x] = nh.GLYPH_PET_OFF + 10 if pet else nh.GLYPH_MON_OFF + 10
        self.monster_tracker.monster_mask[y, x] = True
        self.monster_tracker.peaceful_monster_mask[y, x] = bool(peaceful)
        self.calls = []

    def calc_direction(self, y0, x0, y, x):
        return 'l'

    @contextlib.contextmanager
    def atom_operation(self):
        yield

    def step(self, cmd, *a, **k):
        self.calls.append(('step', cmd))

    def direction(self, d):
        self.calls.append(('dir', d))

    def search(self, n=1):
        self.calls.append(('search', n))

    def log(self, *a, **k):
        pass


def passage(agent):
    dive = types.SimpleNamespace(agent=agent)
    p = CastlePassage(dive)
    p._floating = lambda: False
    return p


def test_peaceful_blocker_waits_with_v2_and_is_fought_without():
    a = FakeAgent(peaceful=True)
    p = passage(a)
    p._step_to(0, 9)                                                   # flag off: the old F + direction
    assert ('step', A.Command.FIGHT) in a.calls and ('search', 1) not in a.calls
    a = FakeAgent(peaceful=True)
    p = passage(a)
    with flags(CASTLE_V2=True):
        for _ in range(jf_config.CASTLE_V2_PEACEFUL_WAITS + 1):
            p._step_to(0, 9)
    assert ('step', A.Command.FIGHT) not in a.calls
    assert a.calls.count(('search', 1)) == jf_config.CASTLE_V2_PEACEFUL_WAITS + 1
    assert a.target in p._route_blocked                                # the route plans round it now
    a = FakeAgent(pet=True)
    p = passage(a)
    with flags(CASTLE_V2=True):
        p._step_to(0, 9)
    assert a.calls == [('search', 1)]                                  # a pet is never fought either
    a = FakeAgent(peaceful=False)
    p = passage(a)
    with flags(CASTLE_V2=True):
        p._step_to(0, 9)
    assert ('step', A.Command.FIGHT) in a.calls                        # hostiles: unchanged
    with flags(CASTLE_V2=True, CASTLE_V2_PEACEFUL=False):
        a = FakeAgent(peaceful=True)
        p = passage(a)
        p._step_to(0, 9)
        assert ('step', A.Command.FIGHT) in a.calls


# ---------------------------------------------------------------- burned engravings and CASTLE_V2_BURN
def parse_with(message):
    agent = types.SimpleNamespace(message=message, popup=[],
                                  panic_if_position_changes=contextlib.nullcontext,
                                  atom_operation=contextlib.nullcontext,
                                  step=lambda *a, **k: None)
    inv = types.SimpleNamespace(agent=agent, _blind_look_skip=lambda: False,
                                _burned_parse_on=Inventory._burned_parse_on)
    Inventory.get_items_below_me(inv, assume_appropriate_message=True)
    return inv.engraving_below_me


def test_burned_engraving_parsed_only_while_active():
    burned = 'Some text has been burned into the floor here.  You read: "Elbereth".  You see no objects here.'
    dust = 'Something is written here in the dust.  You read: "Elbereth".  You see no objects here.'
    with bundle_guard():
        assert parse_with(dust) == 'Elbereth'
        assert parse_with(burned) == ''                               # old behaviour outside castle_v2
        with flags(CASTLE_V2=True):
            castle_v2.apply_bundle()
        assert parse_with(burned) == 'Elbereth'
        assert parse_with(dust) == 'Elbereth'


def test_burn_due_and_fire_wand():
    fire = item('fire', nh.WAND_CLASS, text='a wand of fire (0:4)')
    d, lv, _ = fake_dive(items=[fire])
    with bundle_guard():
        assert castle_v2.fire_wand(d.agent) is fire
        assert not castle_v2.burn_due(d.agent, 0)                     # CASTLE_V2 off
        with flags(CASTLE_V2=True):
            assert not castle_v2.burn_due(d.agent, 0)                 # not active yet (castle zone not reached)
            castle_v2.apply_bundle()
            assert castle_v2.burn_due(d.agent, 0) and castle_v2.burn_due(d.agent, 1)
            assert not castle_v2.burn_due(d.agent, 2)                 # at most 2 tries
            with flags(CASTLE_V2_BURN=False):
                assert not castle_v2.burn_due(d.agent, 0)
    empty = item('fire', nh.WAND_CLASS, comment='EMPT')
    d, lv, _ = fake_dive(items=[empty, item('lightning', nh.WAND_CLASS)])
    assert castle_v2.fire_wand(d.agent) is None                       # empty fire; lightning blinds: not used


# ---------------------------------------------------------------- source checks (NetHack 3.6.6 in NLE 1.3.0)
SRC = os.path.expanduser('~/.cache/uv/sdists-v9/pypi/nle/1.3.0/_0oztOvrHoWSPlUu/src')


def test_source_facts():
    if not os.path.isdir(SRC):
        return
    des = open(os.path.join(SRC, 'dat', 'castle.des')).read()
    assert '$place = { (04,02),(58,02),(04,14),(58,14) }' in des
    assert 'NON_DIGGABLE:(00,00,62,16)' in des and 'FLAGS: noteleport' in des
    assert 'DOOR:locked,(32,04)' in des and 'DOOR:locked,(32,12)' in des
    eng = open(os.path.join(SRC, 'src', 'engrave.c')).read()
    assert 'pline("Some text has been %s into the %s here.",' in eng
    assert 'if (ep->engr_type != BURN || is_ice(x, y) || (magical && !rn2(2))) {' in eng
    lock = open(os.path.join(SRC, 'src', 'lock.c')).read()
    assert 'There("is no obvious way to open the drawbridge.");' in lock
    zap = open(os.path.join(SRC, 'src', 'zap.c')).read()
    assert 'case WAN_STRIKING:\n            case SPE_FORCE_BOLT:\n                if (typ != DRAWBRIDGE_UP)\n' \
           '                    destroy_drawbridge(x, y);' in zap


if __name__ == '__main__':
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} tests passed')
