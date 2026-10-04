"""Unit tests (fakes, no NetHack game) for the cav-kit flags PET_MEAT and TIN_FIX (research/cav_kit.md), plus the
flag-off parity of the touched code with v10c (f3a2a42).

Run from the repo root:  /Users/semyon/Nethack/dev/.venv/bin/python tests/test_cav_kit.py
"""
import ast
import os
import subprocess
import sys
import textwrap
import types

import numpy as np
import nle.nethack as nh

sys.path.insert(0, os.getcwd())

from nhbot import jf_config                        # noqa: E402
from nhbot import objects as O                     # noqa: E402
from nhbot.character import Character             # noqa: E402
from nhbot.glyph import Hunger, MON               # noqa: E402
from nhbot.item import Item                        # noqa: E402
import nhbot.agent as agent_mod                    # noqa: E402
import nhbot.dive_logic as dive_mod                # noqa: E402

A = agent_mod.Agent
BASE = 'f3a2a42'   # v10c


def _base_function(path, cls_name, name):
    """`name` (a method of `cls_name`) as it is at v10c, compiled in the current module's namespace."""
    src = subprocess.run(['git', 'show', f'{BASE}:{path}'], capture_output=True, text=True, check=True).stdout
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    code = textwrap.dedent(ast.get_source_segment(src, sub))
                    # the decorators (Strategy.wrap, debug_log) are not part of the segment: compile the bare function
                    mod = agent_mod if path.endswith('agent.py') else dive_mod
                    ns = dict(vars(mod))
                    exec(code, ns)
                    return ns[name]
    raise AssertionError(f'no {cls_name}.{name} at {BASE}')


class Flags:
    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        self.old = {k: getattr(jf_config, k) for k in self.kw}
        for k, v in self.kw.items():
            setattr(jf_config, k, v)

    def __exit__(self, *a):
        for k, v in self.old.items():
            setattr(jf_config, k, v)


# ------------------------------------------------------------------ fakes

def fake_agent(race=Character.HUMAN, role=Character.CAVEMAN, hunger=Hunger.NOT_HUNGRY, hp=30, maxhp=40, time=1000,
               diving=False):
    bl = types.SimpleNamespace(hunger_state=hunger, hitpoints=hp, max_hitpoints=maxhp, time=time, y=5, x=5)
    ch = Character.__new__(Character)
    ch.race, ch.role = race, role
    ch.were_family = lambda: ()
    logs = []
    shop = np.zeros((21, 79), dtype=bool)
    level = types.SimpleNamespace(shop=shop, corpses_to_eat={})
    f = types.SimpleNamespace(blstats=bl, character=ch, log=logs.append, logs=logs,
                              global_logic=types.SimpleNamespace(dive=types.SimpleNamespace(diving=diving)),
                              current_level=lambda: level, prayer_failed=False, _level=level)
    ch.agent = f
    for name in ('_is_corpse_editable', '_cannibal_allowed', '_food_nutrition', 'ready_food', 'edible_carried_food',
                 '_corpse_refusal'):
        if hasattr(A, name):   # (_corpse_refusal: food-econ's split of _is_corpse_editable, integ and later)
            setattr(f, name, types.MethodType(getattr(A, name), f))
    f._is_tin = A._is_tin
    f._TIN_FIX_FLOOR_SKIP = A._TIN_FIX_FLOOR_SKIP
    f.LIZARD_ID = A.LIZARD_ID
    return f


def food_item(name, count=1, shop_status=Item.NOT_SHOP):
    """A real Item for an unambiguous food object (category, is_corpse and is_unambiguous work as in the game)."""
    obj = O.from_name(name, nh.FOOD_CLASS)
    glyphs = O.possible_glyphs_from_object(obj)
    return Item([obj], glyphs[:1], count=count, status=Item.UNCURSED, shop_status=shop_status, text=f'a {name}')


def with_inventory(f, carried, below=()):
    items = types.SimpleNamespace(all_items=list(carried), main_hand=None)
    eaten = []
    f.inventory = types.SimpleNamespace(items=items, items_below_me=list(below),
                                        eat=lambda item: eaten.append(item.object.name) or True)
    # agent.edible_carried_food reads self.inventory.items through flatten_items (a list works)
    f.inventory.items = _ItemList(carried, items)
    return eaten


class _ItemList(list):
    def __init__(self, carried, ns):
        super().__init__(carried)
        self.all_items = ns.all_items
        self.main_hand = None


# ------------------------------------------------------------------ PET_MEAT

NAMES = ['little dog', 'dog', 'large dog', 'kitten', 'housecat', 'large cat', 'jackal', 'newt', 'kobold', 'acid blob',
         'giant bat', 'werejackal', 'gnome', 'dwarf', 'hill orc', 'human zombie', 'lichen', 'lizard', 'floating eye',
         'cockatrice', 'chameleon', 'yellow mold', 'rothe', 'pony', 'Woodland-elf', 'homunculus', 'killer bee']


def test_corpse_parity_flags_off():
    orig = _base_function('nhbot/agent.py', 'Agent', '_is_corpse_editable')
    n = 0
    with Flags(PET_MEAT=False):
        for race in (Character.HUMAN, Character.ORC, Character.GNOME, Character.ELF, Character.DWARF):
            for role in (Character.CAVEMAN, Character.ROGUE, Character.VALKYRIE, Character.BARBARIAN):
                for hunger, hp in ((Hunger.NOT_HUNGRY, 30), (Hunger.WEAK, 45), (Hunger.FAINTING, 20)):
                    for age in (995, 960, -10000):
                        f = fake_agent(race=race, role=role, hunger=hunger, hp=hp)
                        for name in NAMES:
                            mid = MON.id_from_name(name)
                            assert f._is_corpse_editable(mid, age) == orig(f, mid, age), (race, role, hunger, name)
                            n += 1
    assert n > 4000, n


def test_pet_meat():
    pets = [MON.id_from_name(n) for n in ('little dog', 'dog', 'large dog', 'kitten', 'housecat', 'large cat')]
    cav = fake_agent(race=Character.HUMAN, role=Character.CAVEMAN)
    gno = fake_agent(race=Character.GNOME, role=Character.CAVEMAN)
    orc = fake_agent(race=Character.ORC, role=Character.ROGUE)
    val = fake_agent(race=Character.HUMAN, role=Character.VALKYRIE)
    with Flags(PET_MEAT=False):
        assert not any(f._is_corpse_editable(mid, 995) for f in (cav, gno, orc, val) for mid in pets)
    with Flags(PET_MEAT=True):
        for mid in pets:
            assert cav._is_corpse_editable(mid, 995), MON.permonst(mid).mname
            assert gno._is_corpse_editable(mid, 995)
            assert orc._is_corpse_editable(mid, 995), 'eat.c CANNIBAL_ALLOWED: orcs too'
            assert not val._is_corpse_editable(mid, 995), 'aggravate monster for everyone else'
            assert not cav._is_corpse_editable(mid, 960), 'the age rule still applies'
        # nothing else changes
        jackal, bat = MON.id_from_name('jackal'), MON.id_from_name('giant bat')
        assert cav._is_corpse_editable(jackal, 995) and not cav._is_corpse_editable(bat, 995)


# ------------------------------------------------------------------ TIN_FIX

def test_ready_food_order_and_fainting():
    f = fake_agent(hunger=Hunger.WEAK)
    tin, apple, ration = food_item('tin'), food_item('apple'), food_item('food ration')
    with_inventory(f, [tin, apple, ration])
    names = [i.object.name for i in f.ready_food()]
    assert names == ['food ration', 'apple', 'tin'], names
    f.blstats.hunger_state = Hunger.FAINTING
    names = [i.object.name for i in f.ready_food()]
    assert names == ['food ration', 'apple'], 'no tin while Fainting: ' + str(names)
    with_inventory(f, [tin])
    assert f.ready_food() == [], 'a tin alone is no food while Fainting'
    f.blstats.hunger_state = Hunger.WEAK
    assert [i.object.name for i in f.ready_food()] == ['tin'], 'Weak: the tin may still be tried'


def test_ready_food_floor():
    f = fake_agent(hunger=Hunger.FAINTING)
    tin = food_item('tin')
    floor = [food_item('egg'), food_item('tin'), food_item('food ration'), food_item('apple'),
             food_item('cram ration', shop_status=Item.FOR_SALE)]
    with_inventory(f, [tin], below=floor)
    names = [i.object.name for i in f.ready_food()]
    assert names == ['food ration', 'apple'], 'floor food first, no egg/tin/shop goods: ' + str(names)
    f._level.shop[f.blstats.y, f.blstats.x] = True
    assert f.ready_food() == [], 'never in a shop'
    f._level.shop[:] = False
    f.blstats.hunger_state = Hunger.HUNGRY
    assert [i.object.name for i in f.ready_food()] == ['tin'], 'only Weak or worse eats off the floor'


def _run_eat(f):
    """Drive agent.eat_from_inventory (the Strategy-wrapped generator) to its first decision."""
    gen = _undecorated(A, 'eat_from_inventory')(f)
    first = next(gen)
    if first:
        try:
            next(gen)
        except StopIteration:
            pass
    return first


def _undecorated(cls, name):
    src = open(os.path.join(os.getcwd(), 'nhbot', 'agent.py')).read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls.__name__:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    ns = dict(vars(agent_mod))
                    exec(textwrap.dedent(ast.get_source_segment(src, sub)), ns)
                    return ns[name]
    raise AssertionError(name)


def _eat_agent(hunger, carried, below=()):
    f = fake_agent(hunger=hunger)
    eaten = with_inventory(f, carried, below)
    f.is_safe_to_pray = lambda gap: False
    f.SAFE_HUNGER_PRAYER_GAP = 1700
    f._eat_before_praying = lambda: False
    return f, eaten


def test_eat_from_inventory():
    tin, ration = food_item('tin'), food_item('food ration')
    # flag off: the pack's first food, the tin, again and again (v10c)
    with Flags(TIN_FIX=False):
        f, eaten = _eat_agent(Hunger.FAINTING, [tin], below=[ration])
        assert _run_eat(f) is True and eaten == ['tin']
    with Flags(TIN_FIX=True):
        f, eaten = _eat_agent(Hunger.FAINTING, [tin], below=[ration])
        assert _run_eat(f) is True and eaten == ['food ration'], eaten
        assert any('TIN_FIX eating' in x and 'floor' in x for x in f.logs), f.logs
        f, eaten = _eat_agent(Hunger.FAINTING, [tin])
        assert _run_eat(f) is False and eaten == [], 'the faint guard holds instead'
        f, eaten = _eat_agent(Hunger.WEAK, [tin, food_item('apple')])
        assert _run_eat(f) is True and eaten == ['apple']


def test_eat_from_inventory_parity_off():
    """With TIN_FIX off the strategy is v10c's, decision for decision."""
    orig = _base_function('nhbot/agent.py', 'Agent', 'eat_from_inventory')
    new = _undecorated(A, 'eat_from_inventory')
    cases = [[food_item('tin')], [food_item('apple'), food_item('tin')], [], [food_item('food ration')]]
    with Flags(TIN_FIX=False):
        for hunger in (Hunger.HUNGRY, Hunger.WEAK, Hunger.FAINTING):
            for carried in cases:
                res = []
                for fn in (orig, new):
                    f, eaten = _eat_agent(hunger, carried, below=[food_item('food ration')])
                    g = fn(f)
                    first = next(g)
                    if first:
                        try:
                            next(g)
                        except StopIteration:
                            pass
                    res.append((first, eaten))
                assert res[0] == res[1], (hunger, [i.object.name for i in carried], res)


def _guard_reaches_past_food_check(tin_fix, hunger, carried, below=()):
    """dive_logic.faint_guard up to its food check: True if the guard went past it (it then asks shot_recently)."""
    f, _ = _eat_agent(hunger, carried, below)
    f.prayer_failed = False
    f.camp_hunger = lambda: False
    f.character.prop = types.SimpleNamespace(blind=False)
    f._level.dungeon_number = 0
    f.glyphs = np.zeros((21, 79), dtype=np.int16)
    reached = []
    dive = types.SimpleNamespace(agent=f, rescue=False, diving=False, digging_tool=lambda: None,
                                 _hunt_targets=lambda: [], shot_recently=lambda: reached.append(1) or True)
    raw = None
    src = open(os.path.join(os.getcwd(), 'nhbot', 'dive_logic.py')).read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'faint_guard':
            ns = dict(vars(dive_mod))
            exec(textwrap.dedent(ast.get_source_segment(src, node)), ns)
            raw = ns['faint_guard']
            break
    with Flags(TIN_FIX=tin_fix, FAINT_GUARD=True):
        g = raw(dive)
        assert next(g) is False
    return bool(reached)


def test_faint_guard_food_check():
    tin = food_item('tin')
    assert not _guard_reaches_past_food_check(False, Hunger.FAINTING, [tin]), 'v10c: a carried tin disables the guard'
    assert _guard_reaches_past_food_check(True, Hunger.FAINTING, [tin]), 'TIN_FIX: a tin is no food while Fainting'
    assert not _guard_reaches_past_food_check(True, Hunger.FAINTING, [tin], below=[food_item('food ration')]), \
        'food underfoot: let eat_from_inventory have it'
    assert not _guard_reaches_past_food_check(True, Hunger.WEAK, [tin]), 'Weak: the tin is still food'


def test_ditch_role_config():
    """The Caveman ditch is config: DITCH_PET_ROLES as a JSON list through roles.py works with `in`."""
    import roles
    old_env = os.environ.get('JF_ROLE_CFG')
    old_roles = dive_mod.DITCH_PET_ROLES
    old_hold = jf_config.DITCH_HOLD
    os.environ['JF_ROLE_CFG'] = '{"cav": {"dive_logic.DITCH_PET_ROLES": [2, 4, 9], "jf_config.DITCH_HOLD": true}}'
    try:
        applied = roles.apply('cav-hum-neu-mal')
        assert applied['dive_logic.DITCH_PET_ROLES'] == [2, 4, 9]
        assert Character.CAVEMAN in dive_mod.DITCH_PET_ROLES and Character.SAMURAI in dive_mod.DITCH_PET_ROLES
        assert jf_config.DITCH_HOLD is True
        dl = types.SimpleNamespace(agent=types.SimpleNamespace(character=types.SimpleNamespace(role=Character.CAVEMAN)))
        assert dive_mod.DiveLogic._ditch_pet_role(dl)
    finally:
        dive_mod.DITCH_PET_ROLES = old_roles
        jf_config.DITCH_HOLD = old_hold
        if old_env is None:
            os.environ.pop('JF_ROLE_CFG', None)
        else:
            os.environ['JF_ROLE_CFG'] = old_env


def test_flags_default_off():
    assert jf_config.PET_MEAT is False and jf_config.TIN_FIX is False
    assert Character.CAVEMAN not in dive_mod.DITCH_PET_ROLES


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
            n += 1
    print(n, 'tests passed')
