"""Unit tests (fakes, no NetHack) for PRIEST_BUC and SPELL_KIT (branch pri-cav).
Run from the tree:  cd /Users/semyon/Nethack/pri_cav && ../dev/.venv/bin/python ../research/pri_cav/tests/test_pri_cav.py"""
import os
import sys
import types
from collections import defaultdict

sys.path.insert(0, os.getcwd())

import nle.nethack as nh                       # noqa: E402

from nhbot import jf_config                    # noqa: E402
from nhbot.character import Character          # noqa: E402
from nhbot.glyph import Hunger                 # noqa: E402
import nhbot.agent as agent_mod                # noqa: E402
import nhbot.power_route as pr                 # noqa: E402
import nhbot.opp_items as oi                   # noqa: E402
import nhbot.castle_cross as cc                # noqa: E402

A = agent_mod.Agent


class It:
    def __init__(self, text, category, name=None, equipped=False, objs=()):
        self.text = text
        self.category = category
        self.equipped = equipped
        self.objs = list(objs)
        self.glyphs = [1]
        self.object = types.SimpleNamespace(name=name) if name else None
        self.count = 1

    def is_unambiguous(self):
        return self.object is not None

    def is_armor(self):
        return self.category == nh.ARMOR_CLASS

    def can_be_dropped_from_inventory(self):
        return True


def fake_agent(role, items=()):
    a = types.SimpleNamespace(character=types.SimpleNamespace(role=role))
    a.inventory = types.SimpleNamespace(items=list(items))
    return a


def flags(**kw):
    old = {k: getattr(jf_config, k) for k in kw}
    for k, v in kw.items():
        setattr(jf_config, k, v)
    return old


# ------------------------------------------------------------------------------------------------ PRIEST_BUC

def test_buc_known():
    ring = It('a granite ring', nh.RING_CLASS)
    priest, wiz = fake_agent(Character.PRIEST), fake_agent(Character.WIZARD)
    old = flags(PRIEST_BUC=False)
    try:
        assert not pr.buc_known(ring, priest), 'flag off: unchanged'
        jf_config.PRIEST_BUC = True
        assert pr.buc_known(ring, priest), "a Priest's bare line is uncursed"
        assert not pr.buc_known(ring, wiz), 'other roles unchanged'
        assert not pr.buc_known(ring), 'no agent: unchanged'
        assert pr.buc_known(It('an uncursed granite ring', nh.RING_CLASS), wiz)
        cursed = It('a cursed granite ring', nh.RING_CLASS)
        assert pr.known_cursed(cursed) and pr.buc_known(cursed, priest)
        assert not pr.known_cursed(ring)
    finally:
        flags(**old)


def test_altar_items():
    items = [It('a granite ring', nh.RING_CLASS), It('a scroll labeled FOO', nh.SCROLL_CLASS),
             It('a cursed potion', nh.POTION_CLASS), It('a +1 mace (weapon in hand)', nh.WEAPON_CLASS)]
    old = flags(PRIEST_BUC=False, SCARE_KEEP=False, ALTAR_PICKUP=False)
    try:
        priest = fake_agent(Character.PRIEST, items)
        assert [i.text for i in pr._altar_items(priest)] == ['a granite ring', 'a scroll labeled FOO'], 'flag off'
        jf_config.PRIEST_BUC = True
        assert pr._altar_items(priest) == [], 'a Priest has nothing to BUC-test on an altar'
        wiz = fake_agent(Character.WIZARD, items)
        assert len(pr._altar_items(wiz)) == 2, 'other roles unchanged'
    finally:
        flags(**old)


def test_id_value_tele_scroll_and_water():
    tele = It('a scroll of teleportation', nh.SCROLL_CLASS, name='teleportation')
    tele.object = pr.TELE_SCROLL
    water = It('a potion of water', nh.POTION_CLASS)
    water.object = pr.WATER_POTION
    old = flags(PRIEST_BUC=True)
    try:
        st = types.SimpleNamespace(tc_glyphs=set())
        priest = fake_agent(Character.PRIEST, [tele, water])
        priest._proute = st
        wiz = fake_agent(Character.WIZARD, [tele, water])
        wiz._proute = st
        assert pr._id_value(wiz, tele) == 95, 'a non-Priest still wants to learn the BUC'
        assert pr._id_value(priest, tele) == 0, "a Priest's uncursed teleport scroll is no identify target"
        assert pr._unknown_water(wiz) == [water]
        assert pr._unknown_water(priest) == [], "a Priest's plain water is plain (the gamble dip would blank)"
    finally:
        flags(**old)


def test_opp_buc():
    priest, wiz = fake_agent(Character.PRIEST), fake_agent(Character.WIZARD)
    old = flags(PRIEST_BUC=True)
    try:
        assert oi._buc('a scroll of genocide', priest) == 'noncursed'
        assert oi._buc('a scroll of genocide', wiz) is None
        assert oi._buc('a scroll of genocide') is None
        assert oi._buc('a cursed scroll of genocide', priest) == 'cursed'
        assert oi._buc('a blessed scroll of genocide', wiz) == 'noncursed'
        jf_config.PRIEST_BUC = False
        assert oi._buc('a scroll of genocide', priest) is None
    finally:
        flags(**old)


def test_levitation_boots():
    boots = It('a pair of levitation boots', nh.ARMOR_CLASS, name='levitation boots')
    cursed = It('a cursed pair of levitation boots', nh.ARMOR_CLASS, name='levitation boots')

    def castle(role, items):
        ag = fake_agent(role, items)
        return types.SimpleNamespace(agent=ag, _items=lambda: items)

    old = flags(PRIEST_BUC=False, CFP_MB=False)
    try:
        assert cc._known_lasting_lift(castle(Character.PRIEST, [boots])) is None, 'flag off'
        jf_config.PRIEST_BUC = True
        assert cc._known_lasting_lift(castle(Character.PRIEST, [boots])) == ('boots', boots)
        assert cc._known_lasting_lift(castle(Character.PRIEST, [cursed])) is None
        assert cc._known_lasting_lift(castle(Character.VALKYRIE, [boots])) is None
    finally:
        flags(**old)


# ------------------------------------------------------------------------------------------------ SPELL_KIT

def kit_agent(spells=('protection',), fail=0.05, hp=50, maxhp=60, pw=30, diving=True, near=((0, 11, 11),),
              hunger=Hunger.NOT_HUNGRY, time=5000, cap=0):
    bl = types.SimpleNamespace(hitpoints=hp, max_hitpoints=maxhp, energy=pw, time=time, y=10, x=10,
                               hunger_state=hunger, carrying_capacity=cap)
    prop = types.SimpleNamespace(confusion=False, stun=False, polymorph=False)
    ch = types.SimpleNamespace(known_spells={s: 'abcd'[i] for i, s in enumerate(spells)},
                               spell_fail_chance={s: fail for s in spells}, prop=prop, role=Character.PRIEST)
    f = types.SimpleNamespace(blstats=bl, character=ch, _last_turn=time,
                              last_cast_fail_turn=defaultdict(lambda: -float('inf')),
                              global_logic=types.SimpleNamespace(dive=types.SimpleNamespace(diving=diving)))
    f.get_visible_monsters = lambda: [(d, y, x, None, 0) for d, y, x in near]
    f._SPELL_COST = A._SPELL_COST
    for name in ('_spell_kit_ok', '_spell_kit_diving', '_spell_kit_hostiles', '_spell_kit_choice'):
        setattr(f, name, types.MethodType(getattr(A, name), f))
    return f


def test_spell_kit_choice():
    old = flags(SPELL_KIT=True, SPELL_KIT_HEAL_FRAC=0.65, SPELL_KIT_PROT_RADIUS=2, SPELL_KIT_PROT_GAP=10,
                SPELL_KIT_PW_RESERVE=5, SPELL_KIT_MAX_FAIL=0.25)
    try:
        assert kit_agent()._spell_kit_choice() == ('protection', None)
        assert kit_agent(diving=False)._spell_kit_choice() is None, 'the grind is untouched'
        assert kit_agent(near=((0, 14, 10),))._spell_kit_choice() is None, 'no hostile within 2'
        assert kit_agent(pw=9)._spell_kit_choice() is None, 'Pw reserve'
        assert kit_agent(fail=0.4)._spell_kit_choice() is None, 'too likely to fail'
        assert kit_agent(hunger=Hunger.WEAK)._spell_kit_choice() is None
        assert kit_agent(cap=2)._spell_kit_choice() is None, 'Stressed'
        assert kit_agent(spells=('healing',))._spell_kit_choice() is None, 'healthy: no heal'
        a = kit_agent()
        a._spell_kit_prot_turn = 4995
        assert a._spell_kit_choice() is None, 'protection gap'
        a.blstats.time = 5010
        assert a._spell_kit_choice() == ('protection', None)
        a = kit_agent()
        a.last_cast_fail_turn['protection'] = 4999
        assert a._spell_kit_choice() is None, 'just failed'
        # heals: below 65% with a hostile within 3, extra healing when > 20 HP missing
        assert kit_agent(spells=('healing',), hp=36)._spell_kit_choice() == ('healing', (0, 0))
        assert kit_agent(spells=('healing', 'extra healing'), hp=30)._spell_kit_choice() == \
            ('extra healing', (0, 0))
        assert kit_agent(spells=('healing',), hp=36, near=((0, 15, 15),))._spell_kit_choice() is None
        assert kit_agent(spells=('healing', 'protection'), hp=36, near=((0, 13, 10),))._spell_kit_choice() == \
            ('healing', (0, 0))
        # cure sickness: anywhere, no reserve
        cond = nh.BL_MASK_FOODPOIS
        assert kit_agent(spells=('cure sickness',), pw=15, diving=False)._spell_kit_choice(cond) == \
            ('cure sickness', None)
        assert kit_agent(spells=('cure sickness',), pw=14)._spell_kit_choice(cond) is None
        assert kit_agent(spells=('cure sickness',))._spell_kit_choice(nh.BL_MASK_STONE) is None
        jf_config.SPELL_KIT = False
        assert kit_agent()._spell_kit_choice() is None, 'flag off'
        assert kit_agent(spells=('cure sickness',))._spell_kit_choice(cond) is None
    finally:
        flags(**old)


def test_extra_heal_threshold():
    old = flags(SPELL_KIT=True, SPELL_KIT_HEAL_FRAC=0.65, SPELL_KIT_PW_RESERVE=5, SPELL_KIT_MAX_FAIL=0.25)
    try:
        # 25 of 70 missing (64%): extra healing (> 20 missing) when affordable
        assert kit_agent(spells=('healing', 'extra healing'), hp=45, maxhp=70)._spell_kit_choice() == \
            ('extra healing', (0, 0))
        assert kit_agent(spells=('healing', 'extra healing'), hp=45, maxhp=70, pw=19)._spell_kit_choice() == \
            ('healing', (0, 0)), 'extra healing unaffordable with the reserve'
    finally:
        flags(**old)


def test_cast_nodir():
    events = []
    f = types.SimpleNamespace(message='', blstats=types.SimpleNamespace(time=100), _last_turn=100,
                              last_cast_fail_turn=defaultdict(lambda: -float('inf')),
                              character=types.SimpleNamespace(known_spells={'protection': 'b'}),
                              stats_logger=types.SimpleNamespace(log_event=events.append),
                              _CAST_REFUSED=A._CAST_REFUSED)

    class Atom:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    f.atom_operation = lambda: Atom()
    keys = []

    def step(cmd, gen, reply='The golden haze around you becomes more dense.'):
        keys.extend(list(gen))
        f.message = reply
    f.step = step
    A.cast_nodir(f, 'protection')
    assert keys == ['b'] and events == ['cast_protection'] and f.last_cast_fail_turn['protection'] < 0
    f.step = lambda cmd, gen: (list(gen), setattr(f, 'message', 'You fail to cast the spell correctly.'))
    f.message = ''
    A.cast_nodir(f, 'protection')
    assert events[-1] == 'cast_fail_protection' and f.last_cast_fail_turn['protection'] == 100


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} passed')
