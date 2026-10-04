"""Unit tests (fakes, no NetHack game) for the bar-kit flags (research/bar_kit.md):
MEDUSA_ISLE_HOP, BIMANUAL_KEEP and WEAPON_MODEL_FIX.

Run from the repo root:  /Users/semyon/Nethack/dev/.venv/bin/python tests/test_bar_kit.py
"""
import contextlib
import inspect
import os
import sys

import numpy as np
import nle.nethack as nh

sys.path.insert(0, os.getcwd())

from nhbot import jf_config                                    # noqa: E402
from nhbot import objects as O                                 # noqa: E402
from nhbot.character import Character                         # noqa: E402
from nhbot.dive_logic import DiveLogic                         # noqa: E402
from nhbot.glyph import SS                                     # noqa: E402
from nhbot.item.inventory import Inventory                     # noqa: E402
from nhbot.item.item import Item                               # noqa: E402

MEDUSA = (0, 24)
WATER = SS.S_pool
FLOOR = SS.S_room
TREE = SS.S_tree


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


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


# ----------------------------------------------------------------------------------------------- MEDUSA_ISLE_HOP

class FakeLevel:
    def __init__(self, key=MEDUSA, shape=(21, 79)):
        self._key = key
        self.dungeon_number, self.level_number = key
        self.objects = np.full(shape, WATER, dtype=np.int16)
        self.walkable = np.zeros(shape, dtype=bool)
        self.shop = np.zeros(shape, dtype=bool)
        self.shop_interior = np.zeros(shape, dtype=bool)
        self.stair_destination = {}

    def key(self):
        return self._key

    def land(self, *squares, terrain=FLOOR):
        for y, x in squares:
            self.objects[y, x] = terrain
            self.walkable[y, x] = terrain != TREE


class FakeAgent:
    def __init__(self, level, y, x, capacity=0):
        self.level = level
        self.blstats = Obj(y=y, x=x, time=1000, carrying_capacity=capacity, hitpoints=60, max_hitpoints=80)
        self.glyphs = np.zeros(level.objects.shape, dtype=np.int16)
        self.monster_tracker = Obj(monster_mask=np.zeros(level.objects.shape, dtype=bool))
        self.message = ''
        self.logs = []
        self.dirs = []

    def current_level(self):
        return self.level

    def log(self, s):
        self.logs.append(s)

    def get_visible_monsters(self):
        return []

    @staticmethod
    def calc_direction(fy, fx, ty, tx):
        return ('s' if ty > fy else 'n' if ty < fy else '') + ('e' if tx > fx else 'w' if tx < fx else '')

    def direction(self, d):
        self.dirs.append(d)

    @contextlib.contextmanager
    def atom_operation(self):
        yield


def make_dive(agent, *, tool='pick-axe', wand=None, pit=False, lev=False, freeze=None, on_medusa=True):
    d = object.__new__(DiveLogic)
    d.agent = agent
    d.diving = True
    d.medusa_level = MEDUSA
    d.tasks = []
    d._task = lambda name: d.tasks.append(name)
    d.on_medusa_level = lambda: on_medusa
    d.levitating = lambda: lev
    d._in_own_pit = lambda: pit
    d.digging_tool = lambda: tool
    d.digging_wand = lambda: wand
    d._freeze_action = lambda: freeze
    d._medusa_variant_name = lambda: None     # observed terrain only (no fixed map)
    return d


def islet_world():
    """An isolated hero at (10, 40) (8 moat squares around it); land to the east: (10, 42), (10, 43), (11, 43) (one
    3-square land), and a lone land square (12, 41) south-east of the moat square (11, 41)."""
    level = FakeLevel()
    level.land((10, 40), (10, 42), (10, 43), (11, 43), (12, 41))
    agent = FakeAgent(level, 10, 40)
    return level, agent


def test_isle_hop_off_by_default():
    assert jf_config.MEDUSA_ISLE_HOP is False and jf_config.MEDUSA_ISLE_HOP_MAX == 6
    level, agent = islet_world()
    d = make_dive(agent)
    assert d._isle_hop_action() is None   # the flag gates everything


def test_isle_hop_picks_best_water():
    level, agent = islet_world()
    d = make_dive(agent)
    with flags(MEDUSA_ISLE_HOP=True):
        act = d._isle_hop_action()
    # (10, 41): land neighbours (10, 42) [3-land], (11, 42)? water, plus (12, 41)? not adjacent -> good 1, other 0
    #   share 1 / (1 + 0 + 1) = 0.5;  (11, 41): (10, 42) good, (12, 41) isolated, (12, 42)? water -> 1 / 3
    assert act == ('isle_hop', (10, 41)), act


def test_isle_hop_prefers_higher_share():
    level, agent = islet_world()
    level.land((9, 42))            # (9, 41) now borders (10, 42) and (9, 42): both on the 4-square land
    d = make_dive(agent)
    with flags(MEDUSA_ISLE_HOP=True):
        act = d._isle_hop_action()
    # (9, 41): good 2 -> 2/3 ; (10, 41): (9, 42) and (10, 42) good -> 2/3, orthogonal wins the tie
    assert act == ('isle_hop', (10, 41)), act
    agent.monster_tracker.monster_mask[10, 41] = True    # a monster in that water: never step there
    with flags(MEDUSA_ISLE_HOP=True):
        act = d._isle_hop_action()
    assert act == ('isle_hop', (9, 41)), act


def test_isle_hop_none_when_land_next_to_us():
    level, agent = islet_world()
    level.land((11, 40))           # a land square next to us: a flood crawls us out
    d = make_dive(agent)
    with flags(MEDUSA_ISLE_HOP=True):
        assert d._isle_hop_action() is None


def test_isle_hop_tree_is_not_land():
    level, agent = islet_world()
    level.land((11, 40), terrain=TREE)   # a tree next to us is no crawl destination: still isolated
    d = make_dive(agent)
    with flags(MEDUSA_ISLE_HOP=True):
        assert d._isle_hop_action() is not None


def test_isle_hop_guards():
    level, agent = islet_world()
    with flags(MEDUSA_ISLE_HOP=True):
        assert make_dive(agent, pit=True)._isle_hop_action() is None          # our own pit
        assert make_dive(agent, lev=True)._isle_hop_action() is None          # levitating
        assert make_dive(agent, tool=None, wand=None)._isle_hop_action() is None
        assert make_dive(agent, tool=None, wand='wand')._isle_hop_action() is not None
        assert make_dive(agent, freeze=('freeze', None))._isle_hop_action() is None   # MEDUSA_FREEZE first
        assert make_dive(agent, on_medusa=False)._isle_hop_action() is None
        agent.blstats.carrying_capacity = 2                                   # Stressed
        assert make_dive(agent)._isle_hop_action() is None
        agent.blstats.carrying_capacity = 1                                   # Burdened is fine
        d = make_dive(agent)
        assert d._isle_hop_action() is not None
        d._isle_hops = {MEDUSA: jf_config.MEDUSA_ISLE_HOP_MAX}               # budget spent
        assert d._isle_hop_action() is None


def test_isle_hop_needs_bigger_land():
    level = FakeLevel()
    level.land((10, 40), (10, 42))   # the only other land is a lone square: nothing to dig from there either
    agent = FakeAgent(level, 10, 40)
    d = make_dive(agent)
    with flags(MEDUSA_ISLE_HOP=True):
        assert d._isle_hop_action() is None
    level.land((10, 43))             # now a 2-square land
    with flags(MEDUSA_ISLE_HOP=True):
        assert d._isle_hop_action() == ('isle_hop', (10, 41))


def test_isle_hop_occupied_land_not_counted():
    level, agent = islet_world()
    agent.monster_tracker.monster_mask[10, 42] = True    # a raven on the only good landing next to (10, 41)/(11, 41)
    d = make_dive(agent)
    with flags(MEDUSA_ISLE_HOP=True):
        assert d._isle_hop_action() is None


def test_isle_hop_diagonal_squeeze():
    level = FakeLevel()
    level.land((10, 40), (9, 42), (9, 43), (10, 43))
    level.land((9, 40), (10, 41), terrain=TREE)   # trees N and E of us: the NE water (9, 41) is a squeeze
    level.objects[9, 41] = WATER
    agent = FakeAgent(level, 10, 40)
    d = make_dive(agent)
    with flags(MEDUSA_ISLE_HOP=True):
        act = d._isle_hop_action()
    assert act is None or act[1] != (9, 41), act


def test_isle_hop_map_land_next_to_us():
    level, agent = islet_world()
    d = make_dive(agent)
    land, water = d._isle_terrain()
    land = land.copy()
    water = water.copy()
    land[11, 40], water[11, 40] = True, False      # the variant's map says land there (unseen on screen)
    d._isle_terrain = lambda: (land, water)
    with flags(MEDUSA_ISLE_HOP=True):
        assert d._isle_hop_action() is None


def test_isle_hop_executes_step():
    level, agent = islet_world()
    d = make_dive(agent)
    with flags(MEDUSA_ISLE_HOP=True):
        act = d._isle_hop_action()
        d._escape_act(act)
    assert agent.dirs == ['e'], agent.dirs
    assert d._isle_hops == {MEDUSA: 1}, d._isle_hops
    assert any('MEDUSA_ISLE_HOP 1' in s for s in agent.logs), agent.logs


def test_isle_hop_hooks_are_flag_gated():
    src = inspect.getsource(DiveLogic._dig_escape_action)
    assert 'if jf_config.MEDUSA_ISLE_HOP:\n            hop = self._isle_hop_action()' in src
    src = inspect.getsource(DiveLogic.try_dig_down)
    assert 'if jf_config.MEDUSA_ISLE_HOP:\n            hop = self._isle_hop_action()' in src


# ----------------------------------------------------------------------------------------- weapons and the shield

def item(name, cls=None, *, modifier=0, status=Item.UNCURSED, equipped=False, text=None):
    obj = O.from_name(name, cls) if cls is not None else O.from_name(name)
    it = Item([obj], O.possible_glyphs_from_object(obj), 1, status, modifier, equipped=equipped,
              text=text or name)
    return it


class FakeItems(list):
    def __init__(self, items, main=None, off=None):
        super().__init__(items)
        self.main_hand = main
        self.off_hand = off
        self.suit = None


class FakeEnv:
    @contextlib.contextmanager
    def debug_log(self, txt=None, color=None):
        yield


def make_character(role, skills, *, xl=8, st=18, dx=16):
    agent = Obj(blstats=Obj(experience_level=xl, strength=st, dexterity=dx, time=5000), env=FakeEnv())
    ch = object.__new__(Character)
    ch.agent = agent
    ch.role = role
    ch.skill_levels = np.zeros(64, dtype=int)
    for sub, level in skills.items():
        ch.skill_levels[sub] = level
    agent.character = ch
    return ch


def make_inventory(character, items, main=None, off=None):
    inv = object.__new__(Inventory)
    agent = character.agent
    agent.inventory = inv
    agent.log = lambda s: agent.__dict__.setdefault('logs', []).append(s)
    agent.hands_welded = lambda: False
    character.prop = Obj(polymorph=False)
    inv.agent = agent
    inv.items = FakeItems(items, main, off)
    return inv


def barbarian():
    return make_character(Character.BARBARIAN, {
        O.P_TWO_HANDED_SWORD: Character.SKILL_LEVEL_BASIC, O.P_AXE: Character.SKILL_LEVEL_BASIC,
        O.P_PICK_AXE: Character.SKILL_LEVEL_UNSKILLED, O.P_BARE_HANDED_COMBAT: Character.SKILL_LEVEL_BASIC})


def test_weapon_model_off_is_unchanged():
    ch = barbarian()
    assert Character.weapon_bonus[Character.SKILL_LEVEL_UNSKILLED] == (-4, 2)
    sword = item('two-handed sword', nh.WEAPON_CLASS)
    pick = item('pick-axe')
    lsword = item('long sword', nh.WEAPON_CLASS)
    with flags(WEAPON_MODEL_FIX=False):
        assert ch._get_weapon_skill_bonus(lsword) == (-4, 2)          # the old table (restricted: 0 -> (-4, 2))
        hit, dmg = ch.get_melee_bonus(sword)
        assert dmg == 6.5, dmg
        try:
            ch.get_melee_bonus(pick)
            raise AssertionError('expected the weapon-tool assertion')
        except AssertionError as e:
            assert 'expected' not in str(e), e


def test_weapon_model_fix():
    ch = barbarian()
    sword = item('two-handed sword', nh.WEAPON_CLASS)
    pick = item('pick-axe')
    with flags(WEAPON_MODEL_FIX=True):
        assert ch._get_weapon_skill_bonus(item('long sword', nh.WEAPON_CLASS)) == (-4, -2)
        assert ch._get_weapon_skill_bonus(sword) == (0, 0)
        s_hit, s_dmg = ch.get_melee_bonus(sword)
        p_hit, p_dmg = ch.get_melee_bonus(pick)
    assert p_dmg == 3.5 - 2, p_dmg                     # d6, Unskilled -2
    assert s_hit - p_hit == 4, (s_hit, p_hit)            # Basic 0 vs Unskilled -4 (both hitbon 0)
    arc = make_character(Character.ARCHEOLOGIST, {O.P_PICK_AXE: Character.SKILL_LEVEL_BASIC})
    with flags(WEAPON_MODEL_FIX=True):
        assert arc.get_melee_bonus(pick)[1] == 3.5


def test_bimanual_armorset():
    ch = barbarian()
    sword = item('two-handed sword', nh.WEAPON_CLASS)
    shield = item('small shield', nh.ARMOR_CLASS, equipped=True)
    inv = make_inventory(ch, [sword, shield], main=item('pick-axe'), off=shield)
    with flags(BIMANUAL_KEEP=False):
        assert inv.get_best_armorset()[O.ARM_SHIELD] is shield
    with flags(BIMANUAL_KEEP=True):
        assert inv._bimanual_best() is True
        assert inv.get_best_armorset()[O.ARM_SHIELD] is None
    # a one-handed best weapon keeps the shield
    inv2 = make_inventory(barbarian(), [item('axe', nh.WEAPON_CLASS), shield], off=shield)
    with flags(BIMANUAL_KEEP=True):
        assert inv2._bimanual_best() is False
        assert inv2.get_best_armorset()[O.ARM_SHIELD] is shield


def test_shed_shield():
    ch = barbarian()
    sword = item('two-handed sword', nh.WEAPON_CLASS)
    shield = item('dwarvish roundshield', nh.ARMOR_CLASS, equipped=True)
    inv = make_inventory(ch, [sword, shield], main=item('pick-axe'), off=shield)
    took = []
    inv.takeoff = lambda it: took.append(it) or True
    with flags(BIMANUAL_KEEP=False):
        assert inv.shed_shield_for_bimanual().run(return_condition=True) is False
    assert took == []
    with flags(BIMANUAL_KEEP=True):
        assert inv.shed_shield_for_bimanual().run(return_condition=True) is True
    assert took == [shield], took
    # a refusal backs off for 100 turns
    took.clear()
    inv.takeoff = lambda it: took.append(it) and False
    with flags(BIMANUAL_KEEP=True):
        inv.shed_shield_for_bimanual().run()
        assert inv._bimanual_shed_until == 5100
        assert inv.shed_shield_for_bimanual().run(return_condition=True) is False
    # cursed shields and welded hands are left alone
    inv3 = make_inventory(barbarian(), [sword, item('small shield', nh.ARMOR_CLASS, equipped=True,
                                                    status=Item.CURSED)],
                          off=item('small shield', nh.ARMOR_CLASS, equipped=True, status=Item.CURSED))
    with flags(BIMANUAL_KEEP=True):
        assert inv3.shed_shield_for_bimanual().run(return_condition=True) is False


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for t in tests:
        t()
        print('ok', t.__name__)
    print(f'{len(tests)} tests passed')
