"""Unit tests (fakes, no NetHack game) for INV_FULL_LIST (item/inventory_items.py; port of vkurenkov 4921bc3,
research/competitor_scan2.md N2): an exception raised by a container check mid-parse must not leave the item list cut.
Run from the repo root:  python tests/test_inv_full_list.py"""
import contextlib
import os
import sys

import numpy as np

sys.path.insert(0, os.getcwd())

from nhbot import jf_config                                   # noqa: E402
from nhbot.exceptions import AgentChangeStrategy, AgentPanic  # noqa: E402
from nhbot.item.inventory_items import InventoryItems         # noqa: E402

NO_GLYPH = 5976  # nh.MAX_GLYPH: neither a body nor a statue


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


class FakeItem:
    def __init__(self, name):
        self.name = name
        self.equipped = False
        self.objs = [object()]

    def is_possible_container(self):
        return 'bag' in self.name

    def is_container(self):
        return 'bag' in self.name

    def weight(self):
        return 10

    def __repr__(self):
        return f'FakeItem({self.name!r})'


class FakeItemManager:
    def get_item_from_text(self, text, category=None, glyph=None, position=None):
        return FakeItem(text)


class FakeInventory:
    def __init__(self, exc=None):
        self.item_manager = FakeItemManager()
        self.exc = exc
        self.checked = []

    def check_container_content(self, item):
        self.checked.append(item.name)
        if self.exc is not None:
            raise self.exc('preempted during the bag check')


def observation(entries):
    inv_strs = np.zeros((55, 80), dtype=np.uint8)
    inv_letters = np.zeros(55, dtype=np.uint8)
    inv_oclasses = np.zeros(55, dtype=np.uint8)
    inv_glyphs = np.full(55, NO_GLYPH, dtype=np.int16)
    for i, (letter, name) in enumerate(entries):
        inv_strs[i, :len(name)] = np.frombuffer(name.encode(), dtype=np.uint8)
        inv_letters[i] = ord(letter)
    return {'inv_strs': inv_strs, 'inv_letters': inv_letters, 'inv_oclasses': inv_oclasses, 'inv_glyphs': inv_glyphs}


class FakeAgent:
    def __init__(self, entries, exc=None):
        self.last_observation = observation(entries)
        self.inventory = FakeInventory(exc)
        self.logs = []

    def log(self, msg):
        self.logs.append(msg)

    def get_visible_monsters(self):
        return []


ENTRIES = [('a', 'a +1 long sword (weapon in hand)'), ('J', 'an empty bag named #0'), ('Z', 'a platinum wand'),
           ('b', 'an uncursed food ration')]
ALL_NAMES = sorted(ENTRIES, key=lambda e: e[0])


def _update(agent, inv):
    try:
        inv.update()
    except (AgentChangeStrategy, AgentPanic) as e:
        return e
    return None


def test_off_keeps_the_old_cut_list():
    with flags(INV_FULL_LIST=False):
        agent = FakeAgent(ENTRIES, exc=AgentChangeStrategy)
        inv = InventoryItems(agent)
        err = _update(agent, inv)
        assert isinstance(err, AgentChangeStrategy)
        # letters sort as 'J', 'Z', 'a', 'b' (ASCII): the old parse stops at the bag, the first entry
        assert inv.all_letters == ['J'], inv.all_letters
        # and the cut list survives the next update: the inventory text did not change
        agent.inventory.exc = None
        inv.update()
        assert inv.all_letters == ['J'], inv.all_letters


def test_on_finishes_the_list_then_raises():
    with flags(INV_FULL_LIST=True):
        agent = FakeAgent(ENTRIES, exc=AgentChangeStrategy)
        inv = InventoryItems(agent)
        err = _update(agent, inv)
        assert isinstance(err, AgentChangeStrategy), err
        assert inv.all_letters == [e[0] for e in ALL_NAMES], inv.all_letters
        assert [i.name for i in inv.all_items] == [e[1] for e in ALL_NAMES]
        assert inv.total_weight == 40
        assert agent.inventory.checked == ['an empty bag named #0']
        assert any('INV_FULL_LIST' in m for m in agent.logs)
        # the container is checked again on the next pass (the recheck flag was not cleared)
        assert inv._recheck_containers


def test_on_holds_a_panic_too():
    with flags(INV_FULL_LIST=True):
        agent = FakeAgent(ENTRIES, exc=AgentPanic)
        inv = InventoryItems(agent)
        err = _update(agent, inv)
        assert isinstance(err, AgentPanic), err
        assert len(inv.all_items) == 4


def test_on_without_exception_is_unchanged():
    for on in (False, True):
        with flags(INV_FULL_LIST=on):
            agent = FakeAgent(ENTRIES)
            inv = InventoryItems(agent)
            inv.update()
            assert inv.all_letters == [e[0] for e in ALL_NAMES]
            assert inv.total_weight == 40
            assert not inv._recheck_containers
            assert not agent.logs


def test_flag_defaults_off():
    assert jf_config.INV_FULL_LIST is False


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} passed')
