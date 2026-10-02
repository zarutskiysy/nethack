"""Unit tests (fakes, no NetHack game) for CASTLE_KIT_PICKUP (power.py, item/inventory.py, global_logic.ItemPriority,
dive_logic.kit_dive_pickup; research/strong_castle.md block 3).
Run from the repo root:  python tests/test_castle_kit.py"""
import contextlib
import os
import sys
import types

import nle.nethack as nh
import numpy as np

sys.path.insert(0, os.getcwd())

from nhbot import jf_config                                   # noqa: E402
from nhbot import objects as O                                # noqa: E402
from nhbot import power                                       # noqa: E402
from nhbot.character import Character                         # noqa: E402
from nhbot.dive_logic import DiveLogic                        # noqa: E402
from nhbot.global_logic import ItemPriority                   # noqa: E402
from nhbot.glyph import Hunger                                # noqa: E402
from nhbot.item import Item                                   # noqa: E402
from nhbot.item.inventory import Inventory                    # noqa: E402
from nhbot.level import Level                                 # noqa: E402

H, W = 21, 79


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


def item(name, category=None, count=1, status=Item.UNKNOWN, text=None, objs=None):
    obj = O.from_name(name, category)
    objs = objs or [obj]
    glyph = next(iter(O.possible_glyphs_from_object(objs[0])))
    it = Item(objs, [glyph], count=count, status=status, text=text or name)
    return it


def scare(status=Item.UNCURSED, text=None):
    buc = {Item.UNCURSED: 'uncursed ', Item.BLESSED: 'blessed ', Item.CURSED: 'cursed '}.get(status, '')
    return item('scare monster', nh.SCROLL_CLASS, status=status, text=text or f'a {buc}scroll of scare monster')


# ---------------------------------------------------------------- pickup.c's rule
def test_scare_pickup_outcome_is_pickup_c():
    f = power.scare_pickup_outcome
    assert f(Item.BLESSED, False) == 'unbless' and f(Item.BLESSED, True) == 'unbless'
    assert f(Item.UNCURSED, False) == 'mark'
    assert f(Item.UNCURSED, True) == 'dust'
    assert f(Item.CURSED, False) == 'dust' and f(Item.CURSED, True) == 'dust'
    assert f(Item.UNKNOWN, False) == 'unknown' and f(Item.UNKNOWN, True) == 'dust'


# ---------------------------------------------------------------- inventory rules (unbound, fake self)
class FakeInvSelf:
    _scroll_key = staticmethod(Inventory._scroll_key)
    _droppable = Inventory._droppable
    dropped_here = Inventory.dropped_here
    _note_dropped = Inventory._note_dropped

    def __init__(self, carried=()):
        lvl = types.SimpleNamespace(key=lambda: (0, 27))
        self.agent = types.SimpleNamespace(blstats=types.SimpleNamespace(y=5, x=9), current_level=lambda: lvl,
                                           inventory=self)
        self.scare_labels = set()
        self.dropped_scrolls = set()
        self.items = types.SimpleNamespace(all_items=list(carried))


def test_known_scare_never_dropped_by_arrange_items():
    s = scare()
    inv = FakeInvSelf(carried=[s])
    assert inv._droppable(s) is True                       # flag off: as before
    with flags(CASTLE_KIT_PICKUP=True):
        assert inv._droppable(s) is False
        assert inv._droppable(item('wooden flute')) is True
        unknown = item('scare monster', nh.SCROLL_CLASS,
                       objs=[O.from_name('scare monster', nh.SCROLL_CLASS), O.from_name('identify', nh.SCROLL_CLASS)])
        inv.items.all_items.append(unknown)
        assert inv._droppable(unknown) is True             # (only SCARE_KEEP keeps every candidate)


def test_dropped_scare_never_picked_up_again():
    s = scare()
    inv = FakeInvSelf()
    inv._note_dropped([s], [1])
    assert not inv.dropped_scrolls                          # flag off: not recorded (SCARE_KEEP off)
    with flags(CASTLE_KIT_PICKUP=True):
        inv._note_dropped([s], [1])
        assert inv.dropped_here(s) and not inv.dropped_here(s, (6, 9))
        # blessed in our pack: a pickup only takes the blessing away -- it may come back once
        inv2 = FakeInvSelf()
        b = scare(Item.BLESSED)
        inv2._note_dropped([b], [1])
        assert not inv2.dropped_here(b)
        # a forced drop (the castle base) is never picked up again, blessed or not
        inv2._note_dropped([b], [1], force=True)
        assert inv2.dropped_here(b)


def test_known_cursed_scare_on_the_floor_left_alone():
    inv = FakeInvSelf()
    c = scare(Item.CURSED)
    u = scare(Item.UNCURSED)
    assert not inv.dropped_here(c)                          # flag off
    with flags(CASTLE_KIT_PICKUP=True):
        assert inv.dropped_here(c) and not inv.dropped_here(u)
        assert not inv.dropped_here(scare(Item.UNKNOWN))    # unknown BUC: 7 in 8 survive (and it names the label)


# ---------------------------------------------------------------- ItemPriority
class _Inv:
    def __init__(self, carried):
        self.items = types.SimpleNamespace(all_items=list(carried))
        self.scare_labels = set()

    def get_best_melee_weapon(self, items=None, allow_unknown_status=False):
        return None

    def get_best_armorset(self, items=None, allow_unknown_status=False):
        return []


def _priority(carried=()):
    agent = types.SimpleNamespace(
        blstats=types.SimpleNamespace(time=5000), inventory=_Inv(carried),
        global_logic=types.SimpleNamespace(dive=None),
        character=types.SimpleNamespace(role=Character.PRIEST, alignment=Character.NEUTRAL))
    return ItemPriority(agent)


def test_item_priority_keeps_the_kit_over_food():
    food = item('food ration', count=2)                     # 40
    flute = item('wooden flute')                            # 5
    s = scare()                                             # 5
    items = [food, flute, s]
    ip = _priority()
    counts = ip.split(items, [], 40)[None]
    assert counts == [2, 0, 0], counts                      # flag off: the food takes the weight
    with flags(CASTLE_KIT_PICKUP=True):
        counts = ip.split(items, [], 40)[None]
        assert counts == [1, 1, 1], counts


def test_item_priority_one_instrument_best_first():
    harp = item('wooden harp')
    horn = item('tooled horn', objs=[O.from_name('tooled horn'), O.from_name('horn of plenty')])
    plenty = item('horn of plenty')
    drum = item('leather drum')
    with flags(CASTLE_KIT_PICKUP=True):
        ip = _priority()
        counts = ip.split([horn, plenty, drum, harp], [], 30)[None]
        assert counts[3] == 1 and counts[0] == 0, counts    # the harp (a sure tune) over the unknown horn
        # the one we carry wins a tie (no swapping on the floor)
        f1, f2 = item('wooden flute'), item('wooden flute')
        ip = _priority(carried=[f2])
        counts = ip.split([f1, f2], [], 5)[None]
        assert counts == [0, 1], counts


def test_item_priority_skips_cursed_floor_scare():
    c = scare(Item.CURSED)
    with flags(CASTLE_KIT_PICKUP=True):
        ip = _priority()
        assert not power.kit_floor_dust(ip.agent, scare(Item.UNCURSED))
        assert power.kit_floor_dust(ip.agent, c)


# ---------------------------------------------------------------- the dive's pickup
class FakeDive:
    kit_dive_pickup = DiveLogic.kit_dive_pickup
    _kit_wanted = DiveLogic._kit_wanted
    _kit_has_instrument = DiveLogic._kit_has_instrument
    _kit_item_wanted = DiveLogic._kit_item_wanted

    def __init__(self, below=(), carried=(), glyphs=None, dist=None):
        lvl = types.SimpleNamespace(key=lambda: (0, 9), dungeon_number=Level.DUNGEONS_OF_DOOM,
                                    shop_interior=np.zeros((H, W), bool), shop=np.zeros((H, W), bool))
        self.picked = 0
        self.went = None
        dive = self

        class Inv:
            items = list(carried)
            items_below_me = list(below)
            scare_labels = set()
            dropped_scrolls = set()
            item_manager = types.SimpleNamespace(
                possible_objects_from_glyph=lambda g: list(O.possibilities_from_glyph(g)))

            def dropped_here(self, it, pos=None):
                return False

            def pickup_and_drop_items(self):
                dive.picked += 1
                return types.SimpleNamespace(run=lambda: None)

        self.agent = types.SimpleNamespace(
            current_level=lambda: lvl, inventory=Inv(), log=lambda m: None,
            blstats=types.SimpleNamespace(y=10, x=10, time=100, hitpoints=40, max_hitpoints=40,
                                          hunger_state=Hunger.NOT_HUNGRY),
            get_visible_monsters=lambda: [],
            glyphs=glyphs if glyphs is not None else np.full((H, W), nh.GLYPH_CMAP_OFF, np.int32),
            bfs=lambda: dist, go_to=lambda y, x: setattr(dive, 'went', (y, x)))
        self.diving = True
        self.rescue = False
        self.castle = types.SimpleNamespace(active=lambda: False)

    def on_medusa_level(self):
        return False

    def levitating(self):
        return False

    def _task(self, name):
        pass


def test_dive_picks_up_an_instrument_under_us():
    flute = item('wooden flute')
    d = FakeDive(below=[flute])
    assert d.kit_dive_pickup() is False                       # flag off
    with flags(CASTLE_KIT_PICKUP=True):
        assert d.kit_dive_pickup() is True and d.picked == 1
        assert d.kit_dive_pickup() is False                   # once per square
        # already carrying one: a second instrument is no reason to stop
        d = FakeDive(below=[item('wooden harp')], carried=[item('bugle')])
        assert d.kit_dive_pickup() is False
        # a known scare monster scroll always is
        d = FakeDive(below=[scare()], carried=[item('bugle')])
        assert d.kit_dive_pickup() is True


def test_dive_walks_to_a_near_instrument():
    g = next(iter(O.possible_glyphs_from_object(O.from_name('wooden harp'))))
    glyphs = np.full((H, W), nh.GLYPH_CMAP_OFF, np.int32)
    glyphs[10, 14] = g
    dist = np.full((H, W), -1)
    dist[10, 14] = 4
    with flags(CASTLE_KIT_PICKUP=True):
        d = FakeDive(glyphs=glyphs, dist=dist)
        assert d.kit_dive_pickup() is True and d.went == (10, 14)
        dist[10, 14] = jf_config.PT_KIT_DIST + 1
        d = FakeDive(glyphs=glyphs, dist=dist)
        assert d.kit_dive_pickup() is False
        # a hostile near: no detour
        dist[10, 14] = 4
        d = FakeDive(glyphs=glyphs, dist=dist)
        d.agent.get_visible_monsters = lambda: [(1, 12, 12, None, 0)]
        assert d.kit_dive_pickup() is False


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} tests passed')
