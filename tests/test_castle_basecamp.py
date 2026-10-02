"""Unit tests (fakes, no NetHack game) for CASTLE_BASECAMP and CASTLE_FARM_THEN_ENTER (nhbot/castle_tune.py,
research/strong_castle.md blocks 1-2). Fakes from tests/test_castle_tune.py.
Run from the repo root:  python tests/test_castle_basecamp.py"""
import os
import sys

import nle.nethack as nh

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_castle_tune as T                                  # noqa: E402
from nhbot import jf_config                                   # noqa: E402
from nhbot import objects as O                                # noqa: E402
from nhbot import castle_tune as ctune                        # noqa: E402
from nhbot.castle_logic import WEST_COURTYARD, map_char, to_bot   # noqa: E402
from nhbot.item import Item                                   # noqa: E402
from nle.nethack import actions as A                          # noqa: E402

flags = T.flags
MINO = nh.GLYPH_MON_OFF + 3


class KitItem(T.FakeItem):
    def __init__(self, names, letter, glyph=1000, category=nh.TOOL_CLASS, text=None, status=Item.UNKNOWN):
        if category in (nh.WAND_CLASS, nh.SCROLL_CLASS):
            super().__init__('wooden flute', letter, glyph, category, text)
            self.objs = [O.from_name(names, category)]
            self.object = self.objs[0]
        else:
            super().__init__(names, letter, glyph, category, text)
        self.status = status
        self.shop_status = Item.NOT_SHOP


class Inv(T.Inv):
    """Inventory fake with drop / floor bookkeeping (inventory.py's scare-monster rules)."""

    def __init__(self, agent):
        super().__init__()
        self.agent = agent
        self.items_below_me = []
        self.dropped_scrolls = set()
        self.scare_labels = set()
        self.drops = []

    _scroll_key = staticmethod(lambda item: item.text)

    def drop(self, items, counts):
        for it, c in zip(items, counts):
            self.items.remove(it)
            self.items_below_me.append(it)
            self.drops.append(it)
        self.agent.step_count += 1
        self.agent.blstats.time += 1
        return True

    def _note_dropped(self, items, counts, force=False):
        here = (self.agent.current_level().key(), (int(self.agent.blstats.y), int(self.agent.blstats.x)))
        for it in items:
            self.dropped_scrolls.add(here + (self._scroll_key(it),))

    def is_known_empty(self, item):
        return False

    def get_items_below_me(self):
        pass


class Agent(T.FakeAgent):
    def __init__(self, pos, hp=50, maxhp=50):
        super().__init__(pos, hp, maxhp)
        self.inventory = Inv(self)
        self.blstats.experience_level = 8
        self.engravings = {}

    def direction(self, d):
        before = (self.blstats.y, self.blstats.x)
        super().direction(d)
        if (self.blstats.y, self.blstats.x) != before:
            # the floor under the new square: its own engraving and objects
            self.inventory.engraving_below_me = self.engravings.get((self.blstats.y, self.blstats.x), '')
            self.inventory.items_below_me = []

    def engrave(self, text):
        super().engrave(text)
        self.engravings[(self.blstats.y, self.blstats.x)] = text
        return True


class Dive(T.FakeDive):
    def __init__(self, agent):
        super().__init__(agent)
        self._scare_spot = None


SCARE = 'scare monster'


def setup(pos=(4, 7), tune='CAFEB', items=('wooden flute',), scare=False, hp=50, maxhp=50, **game_kw):
    agent = Agent(pos, hp, maxhp)
    for i, name in enumerate(items):
        agent.inventory.items.append(KitItem(name, 'fghij'[i], glyph=2000 + i))
    if scare:
        agent.inventory.items.append(KitItem(SCARE, 's', glyph=3000, category=nh.SCROLL_CLASS,
                                             text='an uncursed scroll of scare monster', status=Item.UNCURSED))
    agent.game = T.Game(agent, tune=tune, **game_kw)
    dive = Dive(agent)
    return agent, dive, dive.tune


def known_tune(agent, tune, down=True):
    tune.tune = agent.game.tune
    agent.game.known = True
    if down:
        tune._play_tune()
        assert agent.span_state == 'down'


# ---------------------------------------------------------------- flags and geometry
def test_flags_default_off():
    assert jf_config.CASTLE_BASECAMP is False
    assert jf_config.CASTLE_FARM_THEN_ENTER is False
    assert jf_config.CASTLE_KIT_PICKUP is False


def test_camp_squares_are_dry():
    assert ctune.CAMP_SQUARES[0] == ctune.APPROACH == (3, 8)
    for p in ctune.CAMP_SQUARES:
        assert p in WEST_COURTYARD and not ctune.wet(p), p
    for p in ctune.TUNE_SPOTS:
        assert ctune.wet(p)
    assert map_char(*ctune.SPAN) == '}'
    # every camp square is out of a sea monster's reach: no moat square within 1
    assert len(ctune.CAMP_SQUARES) == 12


def test_dry_path_keeps_off_the_water():
    agent, dive, tune = setup(pos=(0, 6))
    path = tune._dry_path((0, 6), (4, 6))
    assert path is not None and path[-1] == (4, 6)
    assert all(not ctune.wet(p) for p in path[:-1]), path
    assert len(path) == 4
    # the plain BFS hugs the moat's edge
    plain = dive.front._path((0, 6), (4, 6))
    assert len(plain) == 4 and any(ctune.wet(p) for p in plain[:-1])


# ---------------------------------------------------------------- the base (a known scroll of scare monster)
def test_base_dropped_on_the_tune_square():
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = setup(scare=True)
        assert tune._step() is True
        assert tune.base == (T.CASTLE_KEY, (4, 7))
        assert [i.text for i in agent.inventory.items_below_me] == ['an uncursed scroll of scare monster']
        assert not any(i.category == nh.SCROLL_CLASS for i in agent.inventory.items)
        y, x = to_bot(4, 7)
        assert dive._scare_spot == (T.CASTLE_KEY, (y, x))
        assert (T.CASTLE_KEY, (y, x), 'an uncursed scroll of scare monster') in agent.inventory.dropped_scrolls
        # on the base: no Elbereth (striking from it would be hypocrisy), the tune search goes on
        assert tune._step() is True
        assert not any(isinstance(s, tuple) and s[0] == 'engrave' for s in agent.steps)
        assert A.Command.APPLY in agent.steps and agent.game.played


def test_base_walk_drops_it_on_arrival():
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = setup(pos=(3, 8), scare=True)
        assert tune._step() is True and tune._pos() in ctune.TUNE_SPOTS
        assert tune._step() is True and tune.base is not None and tune.base[1] == tune._pos()


def test_base_ignores_minotaur_and_strikes_it():
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = setup(scare=True)
        tune._step()                                   # the base
        T.put_monster(agent, (3, 7), 'minotaur', MINO)
        assert tune._danger() is None
        assert tune._step() is True and not tune.done
        assert agent.steps[-1] == A.Command.FIGHT and agent.moves[-1] == 'w'
    # without the base the minotaur still ends the lane
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = setup()
        T.put_monster(agent, (3, 7), 'minotaur', MINO)
        assert tune._step() is False and 'minotaur' in tune.reason


def test_base_with_elbereth_never_strikes():
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True, CASTLE_FARM_THEN_ENTER=True):
        agent, dive, tune = setup(scare=True)
        tune._step()
        agent.inventory.engraving_below_me = 'Elbereth'
        T.put_monster(agent, (5, 7), 'giant eel', T.EEL)
        assert tune._step() is True and A.Command.FIGHT not in agent.steps


def test_eels_fought_from_the_base_only_while_farming():
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = setup(scare=True)
        tune._step()
        T.put_monster(agent, (5, 7), 'giant eel', T.EEL)
        assert tune._step() is True and A.Command.FIGHT not in agent.steps   # (the tune search)
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True, CASTLE_FARM_THEN_ENTER=True):
        agent, dive, tune = setup(scare=True)
        tune._step()
        T.put_monster(agent, (5, 7), 'giant eel', T.EEL)
        assert tune._step() is True and agent.steps[-1] == A.Command.FIGHT and agent.moves[-1] == 'e'
        agent.blstats.hitpoints = 25                      # 0.5 < PT_FARM_EEL_HP: leave it be
        n = len(agent.moves)
        assert tune._step() is True and len(agent.moves) == n


def test_low_hp_on_the_base_rests_there():
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = setup(scare=True, tune='DGABE')
        tune._step()
        known_tune(agent, tune)
        agent.blstats.hitpoints = 10
        assert tune._step() is True and agent.span_state == 'up'      # raised first
        assert tune._step() is True and agent.steps[-1] == 'search'
        assert not tune.done and not tune.paused and tune.camping and tune._pos() == (4, 7)
        agent.blstats.hitpoints = 46                                  # >= PT_CAMP_HP
        assert tune._step() is True and not tune.camping


def test_base_gone_is_noticed():
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = setup(scare=True)
        tune._step()
        assert tune._on_base()
        agent.inventory.items_below_me = [KitItem('dagger', 'z', glyph=1100, category=nh.WEAPON_CLASS)]
        agent.inventory.items_below_me[0].glyphs = [1100]
        assert not tune._on_base() and tune.base is None and tune.base_spent


# ---------------------------------------------------------------- the camp (no scroll)
def test_rest_at_the_camp_before_the_tune_square():
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = setup(pos=(1, 8), hp=30)
        assert tune._step() is True and tune.camping and tune._pos() == (2, 8)
        assert tune._step() is True and tune._pos() == (3, 8)
        assert tune._step() is True and ('engrave', 'Elbereth') in agent.steps
        assert tune._step() is True and agent.steps[-1] == 'search' and tune._pos() == (3, 8)
        agent.blstats.hitpoints = 46
        assert tune._step() is True and not tune.camping
        assert tune._pos() in ctune.TUNE_SPOTS                       # rested: on to the tune square


def test_camp_when_a_sea_monster_shows_and_we_are_hurt():
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = setup(hp=30)                            # 0.6 < PT_CAMP_SEA_HP
        agent.inventory.engraving_below_me = 'Elbereth'
        T.put_monster(agent, (5, 7), 'giant eel', T.EEL)
        assert tune._step() is True and tune.camping
        assert tune._pos() == (3, 8) and agent.moves == ['sw']
    # hurt as much but no sea monster: the lane plays on
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = setup(hp=30)
        agent.inventory.engraving_below_me = 'Elbereth'
        assert tune._step() is True and not tune.camping and A.Command.APPLY in agent.steps


def test_low_hp_camps_instead_of_pausing():
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = setup(hp=10)
        assert tune._step() is True and not tune.paused and tune.camping and tune._pos() == (3, 8)
    # a hostile next to us: the old pause (the survival layers fight)
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = setup(hp=10)
        T.put_monster(agent, (3, 7), 'hill orc')
        assert tune._step() is False and tune.paused and not tune.camping
    # flag off: the old pause
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup(hp=10)
        assert tune._step() is False and tune.paused


class BurnGame(T.Game):
    """engrave.c with a wand of fire: 'You burn into the floor here.' --More-- 'What do you want to burn ...'."""

    def respond(self, action):
        a = self.agent
        if action == A.Command.ENGRAVE:
            self.state = 'with'
            a.misc = [1, 0, 0]
            return 'What do you want to write with? [- w or ?*]'
        if self.state == 'with':
            self.state = 'more'
            a.misc = [0, 0, 1]
            return 'You burn into the floor here.--More--'
        if self.state == 'more' and action == ' ':
            self.state = 'text'
            self.buf = ''
            a.misc = [0, 1, 0]
            return 'What do you want to burn into the floor here?'
        if self.state == 'text':
            if action == '\r':
                self.state = None
                a.misc = [0, 0, 0]
                a.inventory.engraving_below_me = self.buf
                a.burned = self.buf
                return 'Flames fly from the wand.'
            self.buf += action
            return 'What do you want to burn into the floor here? ' + self.buf
        return super().respond(action)


def test_burned_elbereth_with_a_fire_wand():
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = setup(pos=(3, 8), hp=30)
        agent.game = BurnGame(agent)
        agent.inventory.items.append(KitItem('fire', 'w', glyph=nh.GLYPH_OBJ_OFF + 1, category=nh.WAND_CLASS,
                                             text='a wand of fire (0:4)'))
        assert tune._step() is True and tune.camping
        assert getattr(agent, 'burned', None) == 'Elbereth' and tune._engraved()
        assert ('engrave', 'Elbereth') not in agent.steps          # no dust Elbereth


# ---------------------------------------------------------------- the farm
def test_farm_waits_past_the_old_crusher_wait():
    with flags(CASTLE_PASSTUNE=True, CASTLE_FARM_THEN_ENTER=True, PT_FARM_IDLE=40):
        agent, dive, tune = setup(tune='DGABE')
        agent.inventory.engraving_below_me = 'Elbereth'
        known_tune(agent, tune)
        for _ in range(jf_config.PT_CRUSH_WAIT + 5):
            assert tune._step() is True
        assert not tune.handed_off
        r = True
        for _ in range(60):
            r = tune._step()
            if not r:
                break
        assert r is False and tune.handed_off and tune.crusher_over


def test_farm_hands_over_when_strong():
    with flags(CASTLE_PASSTUNE=True, CASTLE_FARM_THEN_ENTER=True):
        agent, dive, tune = setup(tune='DGABE', hp=100, maxhp=100)
        agent.inventory.engraving_below_me = 'Elbereth'
        known_tune(agent, tune)
        assert tune._step() is True and not tune.handed_off           # XL 8
        agent.blstats.experience_level = 11
        assert tune._step() is False and tune.handed_off
        assert any('M:farm_over' in m and 'strong' in m for m in agent.logs)


def test_farm_rests_to_full_before_going_in():
    with flags(CASTLE_PASSTUNE=True, CASTLE_FARM_THEN_ENTER=True):
        agent, dive, tune = setup(tune='DGABE', hp=70, maxhp=100)
        agent.inventory.engraving_below_me = 'Elbereth'
        known_tune(agent, tune)
        agent.blstats.experience_level = 12
        assert tune._step() is True and agent.span_state == 'up' and tune.resting   # 0.7 < PT_FARM_ENTER_HP
        assert tune._step() is True and agent.steps[-1] == 'search'
        agent.blstats.hitpoints = 85                                                # > PT_RESUME_HP, < 0.9
        assert tune._step() is True and agent.steps[-1] == 'search' and agent.span_state == 'up'
        agent.blstats.hitpoints = 95
        assert tune._step() is True and agent.span_state == 'down'
        assert tune._step() is False and tune.handed_off


def test_farm_keeps_crushing_past_the_old_cap():
    with flags(CASTLE_PASSTUNE=True, CASTLE_FARM_THEN_ENTER=True):
        agent, dive, tune = setup(tune='DGABE')
        agent.inventory.engraving_below_me = 'Elbereth'
        known_tune(agent, tune)
        tune.cycles = jf_config.PT_CRUSH_MAX + 5
        T.put_monster(agent, ctune.SPAN)
        assert tune._step() is True and agent.span_state == 'up' and tune.cycles == jf_config.PT_CRUSH_MAX + 6
    with flags(CASTLE_PASSTUNE=True, CASTLE_FARM_THEN_ENTER=True, PT_FARM_RAISES=10):
        agent, dive, tune = setup(tune='DGABE')
        agent.inventory.engraving_below_me = 'Elbereth'
        known_tune(agent, tune)
        tune.cycles = 10
        T.put_monster(agent, ctune.SPAN)
        assert tune._step() is False and tune.handed_off               # budget spent: in, no raise
        assert any('raise budget' in m for m in agent.logs)


def test_farm_turn_budget():
    with flags(CASTLE_PASSTUNE=True, CASTLE_FARM_THEN_ENTER=True, PT_FARM_TURNS=100):
        agent, dive, tune = setup(tune='DGABE')
        agent.inventory.engraving_below_me = 'Elbereth'
        known_tune(agent, tune)
        assert tune._step() is True
        agent.blstats.time += 200
        assert tune._step() is False and tune.handed_off and any('turn budget' in m for m in agent.logs)


def test_flag_off_crusher_unchanged():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup(tune='DGABE')
        agent.inventory.engraving_below_me = 'Elbereth'
        known_tune(agent, tune)
        r = True
        for _ in range(jf_config.PT_CRUSH_WAIT + 5):
            r = tune._step()
            if not r:
                break
        assert r is False and tune.handed_off


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} tests passed')
