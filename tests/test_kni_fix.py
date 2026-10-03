"""Unit tests (fakes, no NetHack game) for DITCH_HOLD and PET_EXILE (research/kni_fix.md).

Run from the repo root:  /Users/semyon/Nethack/dev/.venv/bin/python tests/test_kni_fix.py

The fake world has Dlvl 1 and Dlvl 2 joined by one staircase pair and one tame horse. Stairs follow dog.c keepdogs:
the pet changes level with us only when it is next to us as we take the stairs, and arrives next to us. The pet's
moves are scripted per turn.
"""
import os
import sys
import types

import numpy as np
import nle.nethack as nh

sys.path.insert(0, os.getcwd())

from nhbot import jf_config                                    # noqa: E402
from nhbot import dive_logic as DL                             # noqa: E402
from nhbot import kni_steed as KS                              # noqa: E402
from nhbot.character import Character                         # noqa: E402
from nhbot.global_logic import GlobalLogic, Milestone         # noqa: E402
from nhbot.glyph import MON, SS                                # noqa: E402
from nhbot.level import Level                                  # noqa: E402

D1 = (Level.DUNGEONS_OF_DOOM, 1)
D2 = (Level.DUNGEONS_OF_DOOM, 2)
FLOOR = SS.S_room
DOWN = SS.S_dnstair
UP = SS.S_upstair
PONY = nh.GLYPH_PET_OFF + MON.from_name('pony')
D1_DOWN = (5, 10)
D2_UP = (10, 10)


class FakeLevel:
    def __init__(self, key, stairs, glyph):
        self._key = key
        self.dungeon_number = key[0]
        self.objects = np.full((21, 79), FLOOR, dtype=np.int16)
        self.objects[stairs] = glyph
        self.stair_destination = {}

    def key(self):
        return self._key


class World:
    """pet_script: {turn: (y, x)} -- where the pet stands from that turn on (on whatever level it is)."""

    def __init__(self, pos, pet_pos, pet_level=D1, pet_script=None, always_follow=False):
        self.levels = {D1: FakeLevel(D1, D1_DOWN, DOWN), D2: FakeLevel(D2, D2_UP, UP)}
        self.level = D1
        self.pet_level = pet_level
        self.pet_pos = pet_pos
        self.pet_script = dict(pet_script or {})
        self.always_follow = always_follow


class FakeAgent:
    def __init__(self, world, time=500):
        self.world = world
        self.blstats = types.SimpleNamespace(y=0, x=0, time=time, experience_level=4, hitpoints=30, max_hitpoints=30)
        self.blstats.y, self.blstats.x = world_pos = (3, 3)
        self.pos = world_pos
        self.character = types.SimpleNamespace(role=Character.KNIGHT, prop=types.SimpleNamespace(
            hallu=False, blind=False, confusion=False, stun=False, polymorph=False))
        self.global_logic = types.SimpleNamespace(milestone=Milestone.BE_ON_FIRST_LEVEL,
                                                  steed=types.SimpleNamespace(exile_wanted=lambda: True))
        self.logs = []
        self.actions = []
        self.step_count = 0

    # -- view
    def place(self, pos):
        self.blstats.y, self.blstats.x = pos

    @property
    def glyphs(self):
        g = np.full((21, 79), FLOOR, dtype=np.int16)
        if self.world.pet_level == self.world.level and self.world.pet_pos is not None:
            g[self.world.pet_pos] = PONY
        return g

    def current_level(self):
        return self.world.levels[self.world.level]

    def bfs(self):
        return np.zeros((21, 79), dtype=np.int32)

    def log(self, msg):
        self.logs.append(msg)

    # -- actions
    def _tick(self, n=1):
        for _ in range(n):
            self.blstats.time += 1
            self.step_count += 1
            if self.blstats.time in self.world.pet_script:
                self.world.pet_pos = self.world.pet_script[self.blstats.time]

    def _pet_adjacent(self):
        w = self.world
        if w.pet_level != w.level or w.pet_pos is None:
            return False
        return max(abs(w.pet_pos[0] - self.blstats.y), abs(w.pet_pos[1] - self.blstats.x)) == 1

    def go_to(self, y, x, **_):
        self.actions.append(('go_to', (y, x)))
        d = max(abs(y - self.blstats.y), abs(x - self.blstats.x))
        self.place((y, x))
        self._tick(max(1, d))

    def search(self, *_):
        self.actions.append(('search',))
        self._tick()

    def move(self, y, x=None):
        assert x is None and y in '<>'
        w = self.world
        here = (int(self.blstats.y), int(self.blstats.x))
        if y == '>':
            assert w.level == D1 and here == D1_DOWN, (w.level, here)
            dest, arrive = D2, D2_UP
        else:
            assert w.level == D2 and here == D2_UP, (w.level, here)
            dest, arrive = D1, D1_DOWN
        follows = self._pet_adjacent() or (w.always_follow and w.pet_level == w.level)
        self.actions.append(('stairs', y, follows))
        w.level = dest
        self.place(arrive)
        self.current_level().stair_destination[arrive] = ((D1 if dest == D2 else D2), here)
        if follows:
            w.pet_level = dest
            w.pet_pos = (arrive[0], arrive[1] + 1)
            w.always_follow = False
        self._tick()


def make_dive(agent):
    dive = object.__new__(DL.DiveLogic)
    dive.agent = agent
    dive.diving = False
    dive._ditch_state = 0
    dive._ditch_started = None
    dive._ditch_tries = 0
    dive._ditch_pet_came = False
    dive._pet_hunger_turn = None
    dive._exile_state = 0
    dive._exile_started = None
    dive._exile_tries = 0
    dive._exile_retry_after = -1
    dive.pet_exiled = False
    return dive


def run_strategy(strategy):
    gen = strategy.strategy()
    if not next(gen):
        return False
    try:
        next(gen)
        raise AssertionError('strategy yielded twice')
    except StopIteration:
        return True


class Flags:
    def __init__(self, **kw):
        self.kw = kw
        self.old = {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = getattr(jf_config, k)
            setattr(jf_config, k, v)

    def __exit__(self, *a):
        for k, v in self.old.items():
            setattr(jf_config, k, v)


# ---------------------------------------------------------------------------------------------------- DITCH_HOLD

def test_ditch_hold_leaves_pet_on_dlvl2():
    # the pet trails us to the '>', comes along, stays next to us on Dlvl 2 for 3 turns, then wanders off
    world = World(pos=(3, 3), pet_pos=(5, 9), pet_script={511: (D2_UP[0] + 3, D2_UP[1])})
    agent = FakeAgent(world, time=500)
    agent.place((3, 3))
    dive = make_dive(agent)
    with Flags(DITCH_HOLD=True):
        dive._ditch_state = 1            # what _ditch_pet_check does when it starts an attempt
        dive._ditch_started = agent.blstats.time
        dive._ditch_hold_run()
        # the run went on through the Dlvl 2 arrival (the old code returned there and the tour climbed with the pet)
    assert world.level == D1, world.level
    assert world.pet_level == D2, 'the pet must stay on Dlvl 2'
    assert dive._ditch_state == 3
    assert any('pet left on Dlvl 2: True (held)' in m for m in agent.logs), agent.logs
    stairs = [a for a in agent.actions if a[0] == 'stairs']
    assert stairs == [('stairs', '>', True), ('stairs', '<', False)], stairs


def test_ditch_hold_waits_for_the_pet_at_the_down_stairs():
    world = World(pos=(3, 3), pet_pos=(5, 14), pet_script={510: (5, 12), 512: (5, 11)})
    agent = FakeAgent(world, time=500)
    world.pet_script[520] = (D2_UP[0] + 3, D2_UP[1])   # on Dlvl 2: steps away after a while
    dive = make_dive(agent)
    with Flags(DITCH_HOLD=True):
        dive._ditch_state = 1
        dive._ditch_started = agent.blstats.time
        dive._ditch_hold_run()
    acts = [a[0] for a in agent.actions]
    first_stairs = acts.index('stairs')
    assert 'search' in acts[:first_stairs], 'must wait on the > until the pet is next to us'
    assert world.pet_level == D2 and world.level == D1 and dive._ditch_state == 3


def test_ditch_hold_retries_when_the_pet_did_not_follow():
    # the pet never comes near: the attempt runs out of its budget and returns (state stays 1, the check then ends it)
    world = World(pos=(3, 3), pet_pos=(15, 40))
    agent = FakeAgent(world, time=500)
    dive = make_dive(agent)
    with Flags(DITCH_HOLD=True):
        dive._ditch_state = 1
        dive._ditch_started = agent.blstats.time
        dive._ditch_hold_run()
        assert agent.blstats.time <= 500 + DL.DITCH_PET_BUDGET + 10
        assert world.level == D1
        assert dive._ditch_pet_check(agent.current_level(), D1) is False   # out of time -> retry later


def test_ditch_hold_detects_a_pet_that_came_back_up():
    world = World(pos=(3, 3), pet_pos=(5, 9))
    agent = FakeAgent(world, time=500)
    dive = make_dive(agent)
    with Flags(DITCH_HOLD=True, DITCH_HOLD_STEPS=400):
        dive._ditch_state = 2
        dive._ditch_pet_came = True
        dive._ditch_started = agent.blstats.time
        # we are back on Dlvl 1 and the pet is on screen (it came up with us)
        dive._ditch_hold_run()
    assert dive._ditch_state == 0
    assert any('came back up' in m for m in agent.logs), agent.logs


def test_ditch_strategy_off_path_unchanged():
    # DITCH_HOLD off: the strategy takes one action per call, as before (arrival call: no action)
    world = World(pos=(3, 3), pet_pos=(5, 9))
    agent = FakeAgent(world, time=500)
    agent.place(D1_DOWN)
    world.pet_pos = (5, 11)
    dive = make_dive(agent)
    dive._ditch_pet_role = lambda: True
    with Flags(DITCH_HOLD=False):
        dive._ditch_state = 1
        dive._ditch_started = agent.blstats.time
        assert run_strategy(dive.ditch_pet_strategy())
        assert world.level == D2 and len(agent.actions) == 1
        assert run_strategy(dive.ditch_pet_strategy())
        assert dive._ditch_state == 2 and len(agent.actions) == 1   # the call that returns without acting


# ---------------------------------------------------------------------------------------------------- PET_EXILE

def test_exile_goes_down_alone_and_moves_the_grind():
    world = World(pos=(3, 3), pet_pos=(5, 11), pet_script={})
    agent = FakeAgent(world, time=6000)
    agent.place(D1_DOWN)
    world.pet_script[6002] = (5, 14)   # next to us for two turns, then off
    dive = make_dive(agent)
    with Flags(PET_EXILE=True):
        assert run_strategy(dive.pet_exile_strategy())
    assert world.level == D2 and world.pet_level == D1
    assert dive.pet_exiled and dive._exile_state == 3
    assert [a for a in agent.actions if a[0] == 'stairs'] == [('stairs', '>', False)]
    assert agent.actions[0] == ('search',), 'must not take the stairs with the pet next to us'


def test_exile_turns_into_a_ditch_when_the_pet_comes_along():
    world = World(pos=(3, 3), pet_pos=(7, 15), always_follow=True)
    agent = FakeAgent(world, time=6000)
    world.pet_script[6012] = (D2_UP[0] + 4, D2_UP[1])
    dive = make_dive(agent)
    with Flags(PET_EXILE=True):
        assert run_strategy(dive.pet_exile_strategy())
    assert world.level == D1 and world.pet_level == D2
    assert not dive.pet_exiled and dive._exile_state == 3 and dive._ditch_state == 3
    assert any('pet left on Dlvl 2' in m for m in agent.logs), agent.logs


def test_exile_gates():
    world = World(pos=(3, 3), pet_pos=(7, 15))
    agent = FakeAgent(world, time=6000)
    dive = make_dive(agent)
    with Flags(PET_EXILE=False):
        assert not run_strategy(dive.pet_exile_strategy())
    with Flags(PET_EXILE=True):
        agent.global_logic.steed.exile_wanted = lambda: False
        assert not run_strategy(dive.pet_exile_strategy())
        agent.global_logic.steed.exile_wanted = lambda: True
        agent.character.role = Character.SAMURAI
        assert not run_strategy(dive.pet_exile_strategy())
        agent.character.role = Character.KNIGHT
        dive._ditch_state = 1
        assert not run_strategy(dive.pet_exile_strategy()), 'not during a ditch'
        dive._ditch_state = 3
        agent.global_logic.milestone = Milestone.FIND_GNOMISH_MINES
        assert not run_strategy(dive.pet_exile_strategy())
        agent.global_logic.milestone = Milestone.BE_ON_FIRST_LEVEL
        dive.diving = True
        assert not run_strategy(dive.pet_exile_strategy())
        dive.diving = False
        dive._exile_tries = jf_config.PET_EXILE_TRIES
        assert not run_strategy(dive.pet_exile_strategy())
        assert dive._exile_state == 3
    assert agent.actions == []


def test_grind_level_follows_the_exile():
    gl = object.__new__(GlobalLogic)
    gl.agent = types.SimpleNamespace(character=types.SimpleNamespace(role=Character.KNIGHT),
                                     blstats=types.SimpleNamespace(experience_level=5))
    gl.dive = types.SimpleNamespace(pet_exiled=False)
    with Flags(PET_EXILE=True, ROLE_GRIND_LEVELS={'Knight': {}}, GRIND_LEVELS={5: 3, 7: 2}):
        assert gl._grind_level() is None            # the Knight's Dlvl-1 grind
        gl.dive.pet_exiled = True
        assert gl._grind_level() == 2
    with Flags(PET_EXILE=False, ROLE_GRIND_LEVELS={'Knight': {}}):
        assert gl._grind_level() is None            # flag off: exiled state ignored
    with Flags(PET_EXILE=True, ROLE_GRIND_LEVELS={}, GRIND_LEVELS={5: 3, 7: 2}):
        assert gl._grind_level() == 3               # a deeper table level is kept
        gl.agent.blstats.experience_level = 2
        assert gl._grind_level() == 2               # Dlvl 1 entries are raised to the exile level


# ---------------------------------------------------------------------------------------------------- steed keeper

class FoodItem:
    def __init__(self, name):
        self.category = nh.FOOD_CLASS
        self.objs = [types.SimpleNamespace(name=name, nutrition=50)]
        self.shop_status = 0

    def is_corpse(self):
        return False


def test_exile_wanted():
    world = World(pos=(3, 3), pet_pos=(7, 15))
    agent = FakeAgent(world, time=3000)
    agent.inventory = types.SimpleNamespace(items=[FoodItem('food ration')])
    keeper = KS.SteedKeeper(agent)
    keeper.hungry_at = 2900
    assert not keeper.exile_wanted(), 'no horse seen yet'
    keeper._horse_seen = (D1, 2990)
    assert not keeper.exile_wanted(), 'not yet due to be fed'
    agent.blstats.time = 2900 + KS.FEED_AFTER
    keeper._horse_seen = (D1, agent.blstats.time - 5)
    assert keeper.exile_wanted()
    agent.inventory.items.append(FoodItem('carrot'))
    assert not keeper.exile_wanted(), 'a carrot left: the keeper feeds it'
    agent.inventory.items.pop()
    agent.blstats.time += KS.EXILE_SEEN_WITHIN + 1
    assert not keeper.exile_wanted(), 'horse not seen lately'
    keeper._horse_seen = (D2, agent.blstats.time)
    assert not keeper.exile_wanted(), 'seen on another level'
    keeper._horse_seen = (D1, agent.blstats.time)
    agent.character.role = Character.SAMURAI
    assert not keeper.exile_wanted()


def test_steed_update_records_the_horse():
    world = World(pos=(3, 3), pet_pos=(7, 15))
    agent = FakeAgent(world, time=1234)
    agent.message = ''
    agent.step_count = 7
    keeper = KS.SteedKeeper(agent)
    with Flags(PET_EXILE=False):   # integ: the record is gated (flag off = v10c's update())
        keeper.update()
    assert keeper._horse_seen is None, keeper._horse_seen
    assert keeper._pets == [(7, 15, 'pony')]
    agent.step_count = 8
    with Flags(PET_EXILE=True):
        keeper.update()
    assert keeper._horse_seen == (D1, 1234), keeper._horse_seen
    assert keeper._pets == [(7, 15, 'pony')]


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for t in tests:
        t()
        print('ok', t.__name__)
    print(f'{len(tests)} tests passed')
