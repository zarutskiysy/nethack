"""Unit tests (fakes, no NetHack game) for ARC_WHIP and LOWHP_GAMBLE (branch arc-kit, research/arc_kit.md).
Run from the tree:  cd /Users/semyon/Nethack/arc_kit && ../dev/.venv/bin/python tools/tests/test_arc_kit.py"""
import contextlib
import os
import sys
import types

sys.path.insert(0, os.getcwd())

import numpy as np                              # noqa: E402
import nle.nethack as nh                        # noqa: E402
from nle.nethack import actions as Act          # noqa: E402

from nhbot import jf_config                     # noqa: E402
from nhbot.character import Character           # noqa: E402
from nhbot.dive_logic import DiveLogic          # noqa: E402
from nhbot.glyph import MON                     # noqa: E402
from nhbot.item import Item                     # noqa: E402
import nhbot.agent as agent_mod                 # noqa: E402

A = agent_mod.Agent
H, W = 21, 79


def flags(**kw):
    old = {k: getattr(jf_config, k) for k in kw}
    for k, v in kw.items():
        setattr(jf_config, k, v)
    return old


class It:
    def __init__(self, text, category, name=None, status=Item.UNCURSED, modifier=None, glyph=1):
        self.text = text
        self.category = category
        self.object = types.SimpleNamespace(name=name) if name else None
        self.status = status
        self.modifier = modifier
        self.glyphs = [glyph]
        self.comment = ''

    def is_unambiguous(self):
        return self.object is not None


class Items(list):
    main_hand = None
    off_hand = None

    def get_letter(self, item):
        return 'abcdefghijklmnopqrstuvwxyz'[[id(i) for i in self].index(id(item))]


def blank_glyphs():
    return np.full((H, W), nh.GLYPH_CMAP_OFF, dtype=np.int16)


def fake_agent(role=Character.ARCHEOLOGIST, items=(), main=None, best='whip', dex=12, pos=(10, 40)):
    f = types.SimpleNamespace()
    f.character = types.SimpleNamespace(role=role, prop=types.SimpleNamespace(
        confusion=False, stun=False, polymorph=False, blind=False, hallu=False))
    f.blstats = types.SimpleNamespace(y=pos[0], x=pos[1], dexterity=dex, time=1000, depth=10, hitpoints=40,
                                      max_hitpoints=40, experience_level=5, carrying_capacity=0)
    its = Items(items)
    its.main_hand = main
    f.inventory = types.SimpleNamespace(items=its, engraving_below_me='', is_known_empty=lambda i: False)
    whip = next((i for i in items if i.object is not None and i.object.name == 'bullwhip'), None)
    f.inventory.get_best_melee_weapon = lambda: whip if best == 'whip' else best
    f.glyphs = blank_glyphs()
    f.in_pit = lambda: False
    dive = types.SimpleNamespace(_in_own_pit=lambda: False, diving=True, _hp_history=[], _hurt_on_elbereth=-100,
                                 agent=f)
    dive._lawful_minion = DiveLogic._lawful_minion
    dive._melee_ignores_elbereth = types.MethodType(DiveLogic._melee_ignores_elbereth, dive)
    f.global_logic = types.SimpleNamespace(dive=dive, minetown_level=None)
    f.calc_direction = A.calc_direction
    f._known_uncursed = A._known_uncursed
    f._MZ_LARGE = A._MZ_LARGE
    f._arc_whip = types.MethodType(A._arc_whip, f)
    f.logs = []
    f.log = f.logs.append
    f._note_attack = lambda target=None, direction=None: None
    f.atom_operation = contextlib.nullcontext
    f.keys = []
    f.single_message = ''
    f.message = ''
    f.prompt = 'In what direction?'
    f.result = 'You flick your bullwhip towards the jackal.  You hit the jackal!'

    def step(cmd):
        f.keys.append(cmd)
        if cmd == Act.Command.ESC:
            f.single_message = ''

    def type_text(text):
        f.keys.append(text)
        f.single_message = f.prompt
        f.message = f.prompt

    def direction(d, x=None):
        f.keys.append(('dir', d))
        f.single_message = ''
        f.message = f.result
    f.step, f.type_text, f.direction = step, type_text, direction
    return f


def whip_item(text='a +2 bullwhip (alternate weapon; not wielded)', modifier=2, status=Item.UNCURSED):
    return It(text, nh.WEAPON_CLASS, name='bullwhip', modifier=modifier, status=status)


def pick_item():
    return It('a +0 pick-axe (weapon in hand)', nh.TOOL_CLASS, name='pick-axe', modifier=0)


def put(f, name, y, x):
    g = MON.from_name(name)
    f.glyphs[y, x] = g
    return g


# --------------------------------------------------------------------------------------------- ARC_WHIP

def test_known_uncursed():
    ku = A._known_uncursed
    assert ku(whip_item())                                   # the starting '+2 bullwhip': implicit_uncursed
    assert ku(whip_item('an uncursed bullwhip', modifier=None))
    assert ku(whip_item('a blessed +1 bullwhip', modifier=1))
    assert not ku(whip_item('a bullwhip', modifier=None)), 'unknown BUC (item_manager calls it UNCURSED anyway)'
    assert not ku(whip_item('a cursed +2 bullwhip', modifier=2))


def test_arc_whip_gates():
    whip, pick = whip_item(), pick_item()
    f = fake_agent(items=[whip, pick], main=pick)
    assert f._arc_whip() is whip
    assert fake_agent(role=Character.VALKYRIE, items=[whip, pick], main=pick)._arc_whip() is None, 'Archeologists only'
    assert fake_agent(items=[whip, pick], main=pick, dex=5)._arc_whip() is None, 'Dex 5: proficient 0'
    g = fake_agent(items=[whip, pick], main=pick)
    g.character.prop.confusion = True
    assert g._arc_whip() is None, 'confdir'
    g = fake_agent(items=[whip, pick], main=pick)
    g.character.prop.polymorph = True
    assert g._arc_whip() is None
    cursed_pick = It('a cursed +0 pick-axe (weapon in hand)', nh.TOOL_CLASS, name='pick-axe', status=Item.CURSED)
    assert fake_agent(items=[whip, cursed_pick], main=cursed_pick)._arc_whip() is None, 'welded: no wield_tool'
    unknown = whip_item('a bullwhip', modifier=None)
    assert fake_agent(items=[unknown, pick], main=pick)._arc_whip() is None, 'unknown BUC whip: could weld'
    sword = It('a +1 long sword', nh.WEAPON_CLASS, name='long sword', modifier=1)
    assert fake_agent(items=[whip, pick, sword], main=pick, best=sword)._arc_whip() is None, 'a better weapon'
    g = fake_agent(items=[whip, pick], main=pick)
    g._arc_whip_refused = g.blstats.time - 5
    assert g._arc_whip() is None, 'a refused apply holds it off for 20 turns'
    g.glyphs[0, 0] = next(iter(agent_mod.G.SWALLOW))
    g._arc_whip_refused = -100
    assert g._arc_whip() is None, 'engulfed'


def test_arc_whip_level_ground_disarm():
    whip, pick = whip_item(), pick_item()
    f = fake_agent(items=[whip, pick], main=pick)
    put(f, 'Woodland-elf', 10, 41)
    f.result = "You wrap your bullwhip around the runed broadsword.  You yank the runed broadsword from the " \
               "Woodland-elf's hand!"
    assert A._arc_whip_attack(f, 10, 41) is True
    assert f.keys == [Act.Command.APPLY, 'a', ('dir', 'e')], f.keys
    assert any(s.startswith('ARC_WHIP disarm at the Woodland-elf e (use 1)') for s in f.logs), f.logs
    assert f._arc_whip_disarms == 1
    # the pit yank is not a disarm (use_whip in a pit at a large monster); hallucination: no whip
    f = fake_agent(items=[whip, pick], main=pick)
    put(f, 'jackal', 10, 41)
    f.result = 'You wrap your bullwhip around the jackal.  You yank yourself out of the pit!'
    assert A._arc_whip_attack(f, 10, 41) is True and not getattr(f, '_arc_whip_disarms', 0)
    assert any(s.startswith('ARC_WHIP yanked out of the pit') for s in f.logs), f.logs
    f = fake_agent(items=[whip, pick], main=pick)
    f.character.prop.hallu = True
    assert f._arc_whip() is None


def test_arc_whip_pit_rules():
    whip, pick = whip_item(), pick_item()
    # in our pit, a large monster: use_whip would yank us out of the pit -> the old path
    f = fake_agent(items=[whip, pick], main=pick)
    f.in_pit = lambda: True
    put(f, 'leocrotta', 9, 40)
    assert A._arc_whip_attack(f, 9, 40) is False and f.keys == []
    # the dive's own-pit record counts too
    f = fake_agent(items=[whip, pick], main=pick)
    f.global_logic.dive._in_own_pit = lambda: True
    put(f, 'jaguar', 9, 40)
    assert A._arc_whip_attack(f, 9, 40) is False and f.keys == []
    # in the pit, a medium one with the pick in hand: wield + attack in one action
    f = fake_agent(items=[whip, pick], main=pick)
    f.in_pit = lambda: True
    put(f, 'Green-elf', 11, 39)
    assert A._arc_whip_attack(f, 11, 39) is True and f.keys == [Act.Command.APPLY, 'a', ('dir', 'sw')]
    # in the pit with the whip in hand already: the plain attack is the same -> old path
    f = fake_agent(items=[whip, pick], main=whip)
    f.in_pit = lambda: True
    put(f, 'Green-elf', 11, 39)
    assert A._arc_whip_attack(f, 11, 39) is False and f.keys == []
    # unknown (invisible) target in the pit: size unknown -> old path
    f = fake_agent(items=[whip, pick], main=pick)
    f.in_pit = lambda: True
    f.glyphs[11, 40] = nh.GLYPH_INVISIBLE
    assert A._arc_whip_attack(f, 11, 40) is False


def test_arc_whip_floating_eye_and_refusal():
    whip, pick = whip_item(), pick_item()
    f = fake_agent(items=[whip, pick], main=pick)
    put(f, 'floating eye', 10, 39)
    assert A._arc_whip_attack(f, 10, 39) is False and f.keys == [], 'FEYE_BLIND keeps the eye'
    f = fake_agent(items=[whip, pick], main=pick)
    put(f, 'jackal', 10, 39)
    f.prompt = 'You cannot wield a bullwhip while your pick-axe is welded to your hand.'
    assert A._arc_whip_attack(f, 10, 39) is False
    assert f.keys == [Act.Command.APPLY, 'a', Act.Command.ESC], f.keys
    assert f._arc_whip_refused == f.blstats.time and any('no lash' in s for s in f.logs)


def test_fight2_hook_flag_off_and_on():
    whip, pick = whip_item(), pick_item()
    calls = []
    f = fake_agent(items=[whip, pick], main=pick)
    put(f, 'jackal', 10, 41)
    f.env = types.SimpleNamespace(debug_tiles=lambda *a, **k: contextlib.nullcontext())
    f._keep_digging_tool_wielded = lambda: calls.append('keep') or False
    f.wield_best_melee_weapon = lambda: calls.append('wield') or False
    f.melee_attack = lambda y, x: calls.append(('melee', y, x)) or True
    f._arc_whip_attack = lambda y, x: calls.append(('whip', y, x)) or True
    old = flags(ARC_WHIP=False)
    try:
        assert A._fight2_perform_action(f, ('melee', 0, 1), 3) == 0
        assert calls == ['keep', 'wield', ('melee', 10, 41)], calls
        calls.clear()
        jf_config.ARC_WHIP = True
        assert A._fight2_perform_action(f, ('melee', 0, 1), 3) == 0
        assert calls == [('whip', 10, 41)], calls
        calls.clear()
        f._arc_whip_attack = lambda y, x: calls.append(('whip', y, x)) and False
        A._fight2_perform_action(f, ('melee', 0, 1), 3)
        assert calls == [('whip', 10, 41), 'keep', 'wield', ('melee', 10, 41)], 'a refusal falls back to the old path'
    finally:
        flags(**old)


# ---------------------------------------------------------------------------------------- LOWHP_GAMBLE

def gamble_agent(hp=9, maxhp=40, xl=5, hist=((998, 30), (999, 30), (1000, 9)), items=(), adjacent=('Woodland-elf',),
                 walk=True):
    f = fake_agent(items=list(items))
    f.blstats.hitpoints, f.blstats.max_hitpoints, f.blstats.experience_level = hp, maxhp, xl
    f.global_logic.dive._hp_history = list(hist)
    f._critically_low_hp = types.MethodType(A._critically_low_hp, f)
    mons = []
    for i, name in enumerate(adjacent):
        g = MON.from_name(name)
        y, x = 10, 41 + i
        f.glyphs[y, x] = g
        mons.append((1, y, x, MON.permonst(g), g))
    f.get_visible_monsters = lambda: mons
    f.can_engrave = lambda: True
    f._hurt_recently = lambda turns=3: True
    f._last_resort_zapped = set()
    level = types.SimpleNamespace(walkable=np.full((H, W), walk, dtype=bool), key=lambda: (0, 10))
    f.current_level = lambda: level
    f._free_run = types.MethodType(A._free_run, f)
    f._lowhp_gamble_due = types.MethodType(A._lowhp_gamble_due, f)
    return f


def test_lowhp_gamble_due():
    old = flags(LOWHP_GAMBLE=False, LAST_RESORT=True)
    try:
        f = gamble_agent()
        assert A._lowhp_gamble_due(f) is None, 'flag off'
        jf_config.LOWHP_GAMBLE = True
        adj, why, loss = A._lowhp_gamble_due(f)
        assert why == 'burst' and loss == 21 and adj[0][3].mname == 'Woodland-elf'
        # pray.c critically low (XL5: hp*5 <= maxhp): the last resort proper owns it
        assert A._lowhp_gamble_due(gamble_agent(hp=8)) is None
        # the old 'HP < 12' line without a burst
        assert A._lowhp_gamble_due(gamble_agent(hp=11, hist=((999, 12), (1000, 11))))[1] == 'low'
        # neither: 20/40 after a 2-point scratch
        assert A._lowhp_gamble_due(gamble_agent(hp=20, hist=((999, 22), (1000, 20)))) is None
        # Elbereth holds a jackal: no gamble; blind, the same jackal: Elbereth futile -> gamble
        g = gamble_agent(adjacent=('jackal',))
        assert A._lowhp_gamble_due(g) is None
        g.character.prop.blind = True
        assert A._lowhp_gamble_due(g) is not None
        # not diving / too shallow / nothing next to us / Overtaxed
        g = gamble_agent()
        g.global_logic.dive.diving = False
        assert A._lowhp_gamble_due(g) is None
        g = gamble_agent()
        g.blstats.depth = 4
        assert A._lowhp_gamble_due(g) is None
        assert A._lowhp_gamble_due(gamble_agent(adjacent=())) is None
        g = gamble_agent()
        g.blstats.carrying_capacity = 4
        assert A._lowhp_gamble_due(g) is None
        jf_config.LAST_RESORT = False
        assert A._lowhp_gamble_due(gamble_agent()) is None
    finally:
        flags(**old)


def test_lowhp_gamble_plan_order():
    potion = It('a bubbly potion', nh.POTION_CLASS)
    wand = It('an iron wand', nh.WAND_CLASS, glyph=7)
    scroll = It('a scroll labeled FOO', nh.SCROLL_CLASS)
    known = It('a potion of healing', nh.POTION_CLASS, name='healing')
    old = flags(LOWHP_GAMBLE=True, LAST_RESORT=True, LR_WAND_ONCE=True, KNOWN_ITEMS_RAY_RUN=6)
    orig = agent_mod.combat.fight_heur.missiles_risk_the_watch
    agent_mod.combat.fight_heur.missiles_risk_the_watch = lambda agent: False
    try:
        f = gamble_agent(items=[known, wand, scroll, potion])
        assert A._lowhp_gamble_plan(f)[:2] == ('quaff', potion), 'unknown potions first (known ones: KNOWN_ITEMS)'
        f = gamble_agent(items=[scroll, wand])
        what, item, extra = A._lowhp_gamble_plan(f)
        assert (what, item) == ('zap', wand) and extra[0][3].mname == 'Woodland-elf'
        f._last_resort_zapped.add(7)
        assert A._lowhp_gamble_plan(f)[:2] == ('read', scroll), 'LR_WAND_ONCE'
        f = gamble_agent(items=[scroll, wand], walk=False)
        assert A._lowhp_gamble_plan(f)[:2] == ('read', scroll), 'a wall right behind the target: the ray bounces'
        f = gamble_agent(items=[scroll])
        f.character.prop.blind = True
        assert A._lowhp_gamble_plan(f) is None, 'blind: no unread scroll'
        agent_mod.combat.fight_heur.missiles_risk_the_watch = lambda agent: True
        f = gamble_agent(items=[scroll, wand])
        assert A._lowhp_gamble_plan(f) is None, 'the Watch: no zap, no area scroll'
    finally:
        agent_mod.combat.fight_heur.missiles_risk_the_watch = orig
        flags(**old)


def test_lowhp_gamble_act():
    wand = It('an iron wand', nh.WAND_CLASS, glyph=7)
    f = gamble_agent(items=[wand])
    zaps = []
    f.zap = lambda item, d: zaps.append((item, d))
    target = f.get_visible_monsters()[0]
    A._lowhp_gamble_act(f, ('zap', wand, (target, 'burst')))
    assert zaps == [(wand, 'e')] and 7 in f._last_resort_zapped
    assert any(s.startswith('LOWHP_GAMBLE (burst, hp 9/40): zapping unknown') for s in f.logs), f.logs
    potion = It('a bubbly potion', nh.POTION_CLASS)
    quaffed = []
    f.inventory.quaff = quaffed.append
    A._lowhp_gamble_act(f, ('quaff', potion, 'low'))
    assert quaffed == [potion]


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} passed')
