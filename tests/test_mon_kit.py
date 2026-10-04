"""Unit tests (fakes, no NetHack game) for the Monk kit flags (research/mon_kit.md):
MON_SLEEP_FIGHT (wiz_kit fight lane + minotaur lane for Monks), MON_SHIELD (inventory.get_best_armorset) and
DWARF_ALIGN_HOSTILE (dive_logic ALIGN_BUDGET).

Run from the tree:  cd /Users/semyon/Nethack/mon_kit && ../dev/.venv/bin/python tests/test_mon_kit.py
"""
import os
import sys
import types

import numpy as np

sys.path.insert(0, os.getcwd())

import nle.nethack as nh                              # noqa: E402

from nhbot import castle_power, jf_config             # noqa: E402
from nhbot import dive_logic as DL                    # noqa: E402
from nhbot import mino_guard as MG                    # noqa: E402
from nhbot import objects as O                        # noqa: E402
from nhbot import wiz_kit as W                        # noqa: E402
from nhbot.agent import Agent                         # noqa: E402
from nhbot.character import Character                 # noqa: E402
from nhbot.glyph import G, MON, Hunger                # noqa: E402
from nhbot.item import Item                           # noqa: E402
from nhbot.item.inventory import Inventory            # noqa: E402

FLOOR = next(iter(G.FLOOR))
ROWS, COLS = 21, 79


def flags(module=jf_config, **kw):
    old = {k: getattr(module, k) for k in kw}
    for k, v in kw.items():
        setattr(module, k, v)
    return old


def room(y0, y1, x0, x1):
    w = np.zeros((ROWS, COLS), bool)
    w[y0:y1 + 1, x0:x1 + 1] = True
    return w


# ------------------------------------------------------------------------------------- the wiz_kit fight lane fake

class Thing:
    def __init__(self, cat, name, text=None, equipped=False, glyph=1):
        self.category = cat
        self.object = castle_power._W[name] if cat == nh.WAND_CLASS else types.SimpleNamespace(name=name)
        self.objs = [self.object]
        self.text = text or name
        self.equipped = equipped
        self.modifier = 0
        self.comment = None
        self.status = None
        self.glyphs = [glyph]

    def is_wand(self):
        return self.category == nh.WAND_CLASS

    def is_armor(self):
        return self.category == nh.ARMOR_CLASS

    def is_unambiguous(self):
        return True


def wand(name, n=5):
    return Thing(nh.WAND_CLASS, name, f'a wand of {name} (0:{n})')


ROBE = Thing(nh.ARMOR_CLASS, 'robe', 'an uncursed +1 robe (being worn)', equipped=True)


class ItemList(list):
    def update(self, force=False):
        return None


def mon(name, y, x, hero=(5, 5)):
    g = MON.from_name(name)
    return (max(abs(y - hero[0]), abs(x - hero[1])), y, x, MON.permonst(g), g)


def fake_kit(hostiles=(), walk=None, hp=14, maxhp=55, items=(), spells=None, role=Character.MONK, pw=40,
             race=Character.HUMAN, fail=0.0, diving=True, msg=''):
    hero = (5, 5)
    glyphs = np.full((ROWS, COLS), FLOOR, dtype=np.int16)
    vis = [mon(n, y, x) for n, y, x in hostiles]
    for m in vis:
        glyphs[m[1], m[2]] = m[4]
    walk = room(1, 12, 1, 40) if walk is None else walk
    bl = types.SimpleNamespace(y=hero[0], x=hero[1], hitpoints=hp, max_hitpoints=maxhp, armor_class=3, depth=12,
                               experience_level=8, time=9000, carrying_capacity=0, energy=pw,
                               hunger_state=Hunger.NOT_HUNGRY)
    out = types.SimpleNamespace(logs=[], zaps=[], casts=[], hits=[])
    inv = types.SimpleNamespace(items=ItemList([ROBE] + list(items)), engraving_below_me='', empty_wands=set(),
                                is_known_empty=lambda it: False)
    known = dict(spells or {})
    ch = types.SimpleNamespace(prop=types.SimpleNamespace(blind=False, polymorph=False, stoned=False, confusion=False,
                                                          stun=False, hallu=False),
                               is_lycanthrope=False, role=role, race=race, known_spells=known,
                               spell_fail_chance={k: fail for k in known})
    a = types.SimpleNamespace(
        blstats=bl, glyphs=glyphs, message=msg, log=out.logs.append, character=ch,
        last_observation={'blstats': np.zeros(27, dtype=np.int64)},
        get_visible_monsters=lambda: list(vis),
        current_level=lambda: types.SimpleNamespace(walkable=walk, key=lambda: (0, 12)),
        global_logic=types.SimpleNamespace(minetown_level=None),
        calc_direction=Agent.calc_direction, inventory=inv,
        should_cast_heal=lambda: False, should_cast_extra_heal=lambda: False,
        _keep_digging_tool_wielded=lambda: False, wield_best_melee_weapon=lambda: False)
    inv.agent = a
    a.zap = lambda w, d: out.zaps.append((w.text, d))
    a.cast = lambda s, d: out.casts.append((s, d))
    a.melee_attack = lambda y, x: out.hits.append((y, x))
    dive = types.SimpleNamespace(agent=a, diving=diving, _melee_ignores_elbereth=lambda m: False)
    mino = types.SimpleNamespace(_prayer_first=lambda: False, _read=lambda it, why: None)
    return W.WizKitGuard(dive, mino), a, out


def act(g):
    gen = g.strategy().strategy()
    first = next(gen)
    if first:
        try:
            next(gen)
        except StopIteration:
            pass
    return bool(first)


KIT_OFF = dict(WIZ_WAND_FIGHT=False, WIZ_SPEED_SELF=False, WIZ_KIT_BOOST=False, WIZ_RING_SAFE=False,
               MON_SLEEP_FIGHT=False)


def test_sleep_fight_off_is_inert():
    old = flags(**KIT_OFF)
    try:
        g, a, out = fake_kit(hostiles=[('rothe', 5, 6)], spells={'sleep': 'b'}, items=[wand('striking')])
        assert g.fight_plan() is None
        assert g.kill_plan() is None
        assert not act(g) and not out.casts and not out.zaps
    finally:
        flags(**old)


def test_monk_casts_sleep_at_deadly_rothe():
    old = flags(**dict(KIT_OFF, MON_SLEEP_FIGHT=True))
    try:
        g, a, out = fake_kit(hostiles=[('rothe', 5, 6)], spells={'sleep': 'b'})
        plan = g.fight_plan()
        assert plan is not None and plan[0] == 'cast' and plan[2] == 'sleep' and plan[3] == (0, 1), plan
        a.cast = lambda s, d: (out.casts.append((s, d)), setattr(a, 'message', 'The sleep ray hits the rothe.'))
        assert act(g) and out.casts == [('sleep', (0, 1))], out.casts
        assert (5, 6) in g.slept
        a.message = ''
        assert g.fight_plan() is None, 'the sleeper is no threat'
        assert act(g) and out.hits == [(5, 6)], 'then the sleeper is meleed (martial arts)'
        g, a, out = fake_kit(hostiles=[('rothe', 5, 6)], spells={'sleep': 'b'}, hp=55)
        assert g.fight_plan() is None, 'full HP: no deadly melee yet'
        g, a, out = fake_kit(hostiles=[('rothe', 5, 6)], spells={'sleep': 'b'}, pw=4)
        assert g.fight_plan() is None, 'no Pw'
        g, a, out = fake_kit(hostiles=[('rothe', 5, 6)], spells={'sleep': 'b'}, fail=0.75)
        assert g.fight_plan() is None, 'a heavy shield quartered the chance: no cast'
    finally:
        flags(**old)


def test_monk_resists_its_own_bounce():
    walk = room(5, 5, 2, 6)                  # a dead end right behind the rothe: the ray comes back
    old = flags(**dict(KIT_OFF, MON_SLEEP_FIGHT=True))
    try:
        g, a, out = fake_kit(hostiles=[('rothe', 5, 6)], spells={'sleep': 'b'}, walk=walk)
        assert g._sleep_resistant()
        plan = g.fight_plan()
        assert plan is not None and plan[2] == 'sleep', 'attrib.c mon_abil: a Monk sleeps through nothing'
    finally:
        flags(**old)
    # the same line for a human Wizard (WIZ_WAND_FIGHT): refused, as before
    old = flags(**dict(KIT_OFF, WIZ_WAND_FIGHT=True))
    try:
        g, a, out = fake_kit(hostiles=[('rothe', 5, 6)], spells={'sleep': 'b'}, walk=walk, role=Character.WIZARD)
        assert not g._sleep_resistant()
        assert g.fight_plan() is None
    finally:
        flags(**old)


def test_role_gates():
    old = flags(**dict(KIT_OFF, MON_SLEEP_FIGHT=True))
    try:
        g, a, out = fake_kit(hostiles=[('rothe', 5, 6)], spells={'sleep': 'b'}, role=Character.WIZARD)
        assert g.fight_plan() is None, 'MON_SLEEP_FIGHT is the Monk lane only'
        g, a, out = fake_kit(hostiles=[('rothe', 5, 6)], spells={'sleep': 'b'}, role=Character.PRIEST)
        assert g.fight_plan() is None and not act(g)
    finally:
        flags(**old)
    old = flags(**dict(KIT_OFF, WIZ_WAND_FIGHT=True))
    try:
        g, a, out = fake_kit(hostiles=[('rothe', 5, 6)], spells={'sleep': 'b'})
        assert g.fight_plan() is None, "WIZ_WAND_FIGHT alone stays the Wizards' (WIZ_KIT_ROLES)"
        g, a, out = fake_kit(hostiles=[('rothe', 5, 6)], spells={'sleep': 'b'}, role=Character.WIZARD)
        assert g.fight_plan() is not None, 'the Wizard lane is unchanged'
    finally:
        flags(**old)


def test_monk_uses_found_wands():
    old = flags(**dict(KIT_OFF, MON_SLEEP_FIGHT=True))
    try:
        g, a, out = fake_kit(hostiles=[('rothe', 5, 6)], items=[wand('striking')])
        plan = g.fight_plan()
        assert plan is not None and plan[0] == 'zap' and plan[2] == 'striking', plan
        g, a, out = fake_kit(hostiles=[('rothe', 5, 6)], items=[wand('sleep')], walk=room(5, 5, 2, 6))
        plan = g.fight_plan()
        assert plan is not None and plan[2] == 'sleep', 'a wand of sleep bouncing back is harmless too'
    finally:
        flags(**old)


# ------------------------------------------------------------------------------------- the minotaur lane

MINO = MON.from_name('minotaur')


def fake_mino(mino_at=(5, 8), spells=None, pw=40, fail=0.0, role=Character.MONK, msg=''):
    hero = (5, 5)
    glyphs = np.full((ROWS, COLS), FLOOR, dtype=np.int16)
    glyphs[mino_at] = MINO
    bl = types.SimpleNamespace(y=hero[0], x=hero[1], hitpoints=50, max_hitpoints=55, depth=26, experience_level=8,
                               time=12000, carrying_capacity=0, energy=pw, hunger_state=Hunger.NOT_HUNGRY)
    out = types.SimpleNamespace(logs=[], casts=[], zaps=[], digs=[])
    known = dict(spells or {})
    ch = types.SimpleNamespace(role=role, known_spells=known, spell_fail_chance={k: fail for k in known},
                               prop=types.SimpleNamespace(blind=False, polymorph=False, hallu=False, confusion=False,
                                                          stun=False))
    level = types.SimpleNamespace(key=lambda: (0, 26), dungeon_number=0, walkable=room(1, 12, 1, 40),
                                  objects=np.full((ROWS, COLS), FLOOR, dtype=np.int16))
    a = types.SimpleNamespace(blstats=bl, glyphs=glyphs, message=msg, step_count=1, character=ch, log=out.logs.append,
                              current_level=lambda: level, calc_direction=Agent.calc_direction,
                              monster_tracker=types.SimpleNamespace(
                                  peaceful_monster_mask=np.zeros((ROWS, COLS), bool)))
    a.cast = lambda s, d: out.casts.append((s, d))
    dive = types.SimpleNamespace(agent=a, on_scare_scroll=lambda: False)
    g = MG.MinoGuard(dive)
    # the parts of the plan before step 2a, stubbed: nothing to dig with, no wand, no instrument, no prayer due
    g._diggable = lambda: False
    g._prayer_first = lambda: False
    g._wand = lambda names: (None, None)
    g._instruments = lambda: {}
    # ...and after it: no stairs, no teleport, no scrolls, no unknown wands
    g._ups = lambda: []
    g._teleport_ok = lambda: False
    g._scroll = lambda *args, **kw: None
    g._sleep_or_death = lambda: None
    g._unknown_wand = lambda sy, sx: (None, None)
    g._unknown_scroll = lambda: (None, 0)
    return g, a, out


def first_plan(g):
    return next(iter(g._candidates()), None)


def test_mino_lane_casts_sleep():
    old = flags(MON_SLEEP_FIGHT=False)
    try:
        g, a, out = fake_mino(spells={'sleep': 'b'})
        kinds = [p[0] for p in _first_n(g, 1)]
        assert 'cast_sleep' not in kinds, 'flag off: no spell in the lane'
    finally:
        flags(**old)
    old = flags(MON_SLEEP_FIGHT=True)
    try:
        g, a, out = fake_mino(spells={'sleep': 'b'})
        plan = first_plan(g)
        assert plan is not None and plan[0] == 'cast_sleep' and plan[1][0] == (0, 1), plan
        def cast(s, d):   # a cast is a game step: the message changes and step_count moves on
            out.casts.append((s, d))
            a.step_count += 1
            a.message = 'The sleep ray hits the minotaur.'
        a.cast = cast
        g._act(plan)
        assert out.casts == [('sleep', (0, 1))], out.casts
        assert g._frozen((3, 5, 8, None)), 'the hit froze it (_note): the dig-out follows'
        g, a, out = fake_mino(spells={'sleep': 'b'}, mino_at=(7, 8))
        assert all(p[0] != 'cast_sleep' for p in _first_n(g, 5)), 'not in line'
        g, a, out = fake_mino(spells={'sleep': 'b'}, pw=3)
        assert all(p[0] != 'cast_sleep' for p in _first_n(g, 5)), 'no Pw'
        g, a, out = fake_mino(spells={'sleep': 'b'}, role=Character.WIZARD)
        assert all(p[0] != 'cast_sleep' for p in _first_n(g, 5)), 'Monks only'
        g, a, out = fake_mino(spells={'healing': 'b'})
        assert all(p[0] != 'cast_sleep' for p in _first_n(g, 5)), 'no sleep spell'
    finally:
        flags(**old)


def _first_n(g, n):
    out = []
    for p in g._candidates():
        out.append(p)
        if len(out) >= n:
            break
    return out


# ------------------------------------------------------------------------------------- MON_SHIELD

def armor(name, ac_bonus=0, equipped=False):
    obj = O.from_name(name)
    it = types.SimpleNamespace(object=obj, objs=[obj], status=Item.UNCURSED, equipped=equipped, text=name)
    it.is_armor = lambda: True
    it.is_unambiguous = lambda: True
    it.is_container = lambda: False
    it.get_ac = lambda: obj.ac - ac_bonus         # as Item.get_ac: objects.c's 10 - AC bonus, minus the enchantment
    return it


def best_shield(role, items):
    me = types.SimpleNamespace(agent=types.SimpleNamespace(character=types.SimpleNamespace(role=role)), items=items)
    best = Inventory.get_best_armorset(me, items=items)
    s = best[O.ARM_SHIELD]
    return None if s is None else s.object.name


def test_mon_shield():
    small, round_, refl = armor('small shield'), armor('dwarvish roundshield'), armor('shield of reflection')
    helm = armor('dwarvish iron helm')
    old = flags(MON_SHIELD=0)
    try:
        assert best_shield(Character.MONK, [small, round_, helm]) == 'dwarvish roundshield', 'off: the AC 2 shield'
    finally:
        flags(**old)
    old = flags(MON_SHIELD=1)
    try:
        assert best_shield(Character.MONK, [small, round_, helm]) == 'small shield'
        assert best_shield(Character.MONK, [round_, refl]) == 'shield of reflection'
        assert best_shield(Character.VALKYRIE, [small, round_]) == 'dwarvish roundshield', 'Monks only'
        me = types.SimpleNamespace(agent=types.SimpleNamespace(character=types.SimpleNamespace(role=Character.MONK)))
        best = Inventory.get_best_armorset(me, items=[small, round_, helm])
        assert best[O.ARM_HELM] is helm, 'the other slots are untouched'
    finally:
        flags(**old)
    old = flags(MON_SHIELD=2)
    try:
        assert best_shield(Character.MONK, [small, round_, helm]) is None
        assert best_shield(Character.MONK, [small, refl]) == 'shield of reflection'
    finally:
        flags(**old)


# ------------------------------------------------------------------------------------- DWARF_ALIGN_HOSTILE

def fake_dive(race, alignment, est=10, msg=''):
    d = DL.DiveLogic.__new__(DL.DiveLogic)
    ch = types.SimpleNamespace(race=race, alignment=alignment)
    d.agent = types.SimpleNamespace(character=ch, _message_history=[msg] if msg else [],
                                    glyphs=np.full((ROWS, COLS), FLOOR, dtype=np.int16),
                                    blstats=types.SimpleNamespace(y=5, x=5, hunger_state=Hunger.NOT_HUNGRY),
                                    log=lambda s: None)
    d._align_est = est
    d._dwarves_killed = 0
    d._history_seen2 = 0
    d._dwarf_seen = (None, [])
    d._fetch_given_up = set()
    d.tool_spots = set()
    d._crash_turn = {}
    d._diggers = {}
    return d


def test_dwarves_always_hostile_table():
    H, E, D, Gn, Or = Character.HUMAN, Character.ELF, Character.DWARF, Character.GNOME, Character.ORC
    L, N, C = Character.LAWFUL, Character.NEUTRAL, Character.CHAOTIC
    cases = {(H, N): True, (H, C): True, (H, L): False, (E, C): True, (Or, C): True, (D, L): False,
             (Gn, N): False, (H, Character.UNKNOWN): False}
    for (race, al), want in cases.items():
        assert fake_dive(race, al)._dwarves_always_hostile() is want, (race, al)


def test_may_kill_dwarf_budget():
    old = flags(DL, ALIGN_BUDGET=True, DWARF_ALIGN_HOSTILE=False)
    try:
        assert not fake_dive(Character.HUMAN, Character.NEUTRAL, est=10)._may_kill_dwarf(), 'off: the false debt'
        assert fake_dive(Character.HUMAN, Character.NEUTRAL, est=40)._may_kill_dwarf()
    finally:
        flags(DL, **old)
    old = flags(DL, ALIGN_BUDGET=True, DWARF_ALIGN_HOSTILE=True)
    try:
        assert fake_dive(Character.HUMAN, Character.NEUTRAL, est=10)._may_kill_dwarf()
        assert fake_dive(Character.HUMAN, Character.NEUTRAL, est=None)._may_kill_dwarf()
        assert not fake_dive(Character.HUMAN, Character.LAWFUL, est=10)._may_kill_dwarf(), 'lawful: budget as before'
        assert fake_dive(Character.HUMAN, Character.LAWFUL, est=40)._may_kill_dwarf()
    finally:
        flags(DL, **old)


def test_align_estimate_after_dwarf_kill():
    level = types.SimpleNamespace(dungeon_number=2, objects=np.full((ROWS, COLS), FLOOR, dtype=np.int16))
    old = flags(DL, ALIGN_BUDGET=True, DWARF_ALIGN_HOSTILE=False)
    try:
        d = fake_dive(Character.HUMAN, Character.NEUTRAL, est=40, msg='You kill the dwarf!')
        d._observe_dwarves((2, 1), level, 9000)
        assert d._align_est == 28, d._align_est
    finally:
        flags(DL, **old)
    old = flags(DL, ALIGN_BUDGET=True, DWARF_ALIGN_HOSTILE=True)
    try:
        d = fake_dive(Character.HUMAN, Character.NEUTRAL, est=40, msg='You kill the dwarf!')
        d._observe_dwarves((2, 1), level, 9000)
        assert d._align_est == 42, d._align_est
        d = fake_dive(Character.HUMAN, Character.LAWFUL, est=40, msg='You kill the dwarf lord!')
        d._observe_dwarves((2, 1), level, 9000)
        assert d._align_est == 25, 'a lawful human: -15 as before'
    finally:
        flags(DL, **old)


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for t in tests:
        t()
        print('ok', t.__name__)
    print(f'{len(tests)} tests passed')
