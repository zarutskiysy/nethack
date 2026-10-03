"""Unit tests (fakes, no NetHack games) for QUEST_DIVE (research/quest_dive.md).
Run from the repo root:  python tests/test_quest_dive.py"""
import contextlib
import os
import sys

import numpy as np

sys.path.insert(0, os.getcwd())

from nhbot import dive_logic as DL                            # noqa: E402
from nhbot import jf_config                                   # noqa: E402
from nhbot.glyph import MON, SS                                # noqa: E402
from nhbot.level import Level                                 # noqa: E402

NORN = MON.from_name('Norn')


class BL:
    def __init__(self, xl=14, hp=100, maxhp=100, y=10, x=40, time=20000):
        self.experience_level = xl
        self.hitpoints, self.max_hitpoints = hp, maxhp
        self.y, self.x = y, x
        self.time = time
        self.depth = 13


class Lvl:
    def __init__(self, dlevel):
        self.dungeon_number, self.level_number = Level.QUEST, dlevel
        self.objects = np.full((21, 79), -1, dtype=np.int16)

    def key(self):
        return (self.dungeon_number, self.level_number)


class FakeAgent:
    def __init__(self, dlevel=1, **bl):
        self.level = Lvl(dlevel)
        self.blstats = BL(**bl)
        self.glyphs = np.zeros((21, 79), dtype=np.int16)
        self.message = ''
        self.logs, self.calls = [], []

    def current_level(self):
        return self.level

    def log(self, msg):
        self.logs.append(msg)

    def go_to(self, y, x, stop_one_before=False):
        self.calls.append(('go_to', y, x, stop_one_before))

    def move(self, d):
        self.calls.append(('move', d))

    def step(self, action):
        self.calls.append(('step', action))

    def direction(self, d):
        self.calls.append(('direction', d))

    @staticmethod
    def calc_direction(y0, x0, y, x):
        return {(0, 1): 'e', (0, -1): 'w', (1, 0): 's', (-1, 0): 'n',
                (1, 1): 'se', (1, -1): 'sw', (-1, 1): 'ne', (-1, -1): 'nw'}[(y - y0, x - x0)]

    @contextlib.contextmanager
    def atom_operation(self):
        yield


class FakeExploration:
    def __init__(self, calls):
        self.calls = calls

    def until(self, agent, cond):
        self.calls.append('explore')
        return self

    def run(self):
        pass


class FakeDive:
    quest_dive_step = DL.DiveLogic.quest_dive_step
    _quest_meet_leader = DL.DiveLogic._quest_meet_leader
    leave_quest = DL.DiveLogic.leave_quest
    QUEST_LEADERS = DL.DiveLogic.QUEST_LEADERS

    def __init__(self, agent):
        self.agent = agent
        self.tasks = []
        self.quest_arrival = None

    def _task(self, name):
        self.tasks.append(name)

    def rest_if_hurt(self):
        return False

    def _take_stairs(self, stairs, direction):
        self.agent.calls.append(('take_stairs', tuple(stairs), direction))
        return True

    def _budgeted(self, cond):
        return cond

    def exploration(self, prio):
        return FakeExploration(self.agent.calls)

    def return_to_main_dungeon(self):
        self.agent.calls.append('climb')


def make(dlevel=1, **bl):
    agent = FakeAgent(dlevel, **bl)
    return FakeDive(agent), agent


def test_leader_names_resolve():
    for name in DL.DiveLogic.QUEST_LEADERS:
        MON.from_name(name)   # asserts on an unknown name


def test_low_xl_gives_up():
    dive, agent = make(xl=13)
    assert dive.quest_dive_step() is False
    assert any('XL 13 < 14' in m for m in agent.logs)
    agent.blstats.experience_level = 14
    assert dive.quest_dive_step() is False      # never restarts
    assert agent.calls == []


def test_mysterious_force_gives_up():
    dive, agent = make()
    agent.message = 'A mysterious force prevents you from descending.  The fire giant hits!'
    assert dive.quest_dive_step() is False
    assert any('mysterious force' in m for m in agent.logs)


def test_home5_banked_and_hurt():
    dive, agent = make(dlevel=5)
    assert dive.quest_dive_step() is False
    assert any('Home 5 banked' in m for m in agent.logs)
    dive, agent = make(dlevel=2, hp=40)
    assert dive.quest_dive_step() is False
    assert any('hurt' in m for m in agent.logs)


def test_budget():
    dive, agent = make(dlevel=2)
    agent.level.objects[3, 3] = SS.S_dnstair
    assert dive.quest_dive_step() is True
    agent.blstats.time += jf_config.QUEST_DIVE_TURNS + 1
    assert dive.quest_dive_step() is False
    assert any('out of budget' in m for m in agent.logs)


def test_chat_with_adjacent_leader():
    dive, agent = make(y=10, x=40)
    agent.glyphs[10, 41] = NORN
    assert dive.quest_dive_step() is True
    assert ('step', DL.A.Command.CHAT) in agent.calls
    assert ('direction', 'e') in agent.calls
    assert dive._qdive['leader'] is True
    # next step: the stairs
    agent.level.objects[2, 20] = SS.S_dnstair
    agent.calls.clear()
    assert dive.quest_dive_step() is True
    assert agent.calls == [('take_stairs', ((2, 20),), '>')]


def test_walk_to_distant_leader_then_look_for_him():
    dive, agent = make(y=10, x=10)
    agent.glyphs[11, 37] = NORN
    assert dive.quest_dive_step() is True
    assert agent.calls == [('go_to', 11, 37, True)]
    agent.glyphs[11, 37] = 0
    agent.calls.clear()
    assert dive.quest_dive_step() is True
    assert agent.calls == ['explore']


def test_leader_search_times_out_to_stairs():
    dive, agent = make()
    agent.level.objects[2, 20] = SS.S_dnstair
    assert dive.quest_dive_step() is True          # looks for the leader
    agent.blstats.time += jf_config.QUEST_DIVE_LEADER_TURNS + 1
    agent.calls.clear()
    assert dive.quest_dive_step() is True
    assert agent.calls == [('take_stairs', ((2, 20),), '>')]


def test_press_down_on_stairs_and_give_up_after_three():
    dive, agent = make(dlevel=3, y=5, x=5)
    agent.level.objects[5, 5] = SS.S_dnstair
    for _ in range(3):
        assert dive.quest_dive_step() is True
    assert agent.calls == [('move', '>')] * 3
    assert dive.quest_dive_step() is False
    assert any("did not take us down" in m for m in agent.logs)


def test_explore_when_no_stairs_known():
    dive, agent = make(dlevel=2)
    assert dive.quest_dive_step() is True
    assert agent.calls == ['explore']


def test_leave_quest_climbs_from_below_home():
    dive, agent = make(dlevel=4)
    dive.leave_quest()
    assert agent.calls == ['climb']


def test_flag_default_off():
    assert jf_config.QUEST_DIVE is False


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            DL.DiveLogic._LEADER_GLYPHS = None
            fn()
            n += 1
            print('ok', name)
    print(f'{n} tests passed')
