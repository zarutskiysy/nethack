"""Unit tests (fakes, no NetHack game) for CASTLE_PASSTUNE (nhbot/castle_tune.py, research/castle_entry.md).
Run from the repo root:  python tests/test_castle_tune.py"""
import contextlib
import os
import random
import sys

import nle.nethack as nh
import numpy as np

sys.path.insert(0, os.getcwd())

from nhbot import jf_config                                   # noqa: E402
from nhbot import objects as O                                # noqa: E402
from nhbot import castle_tune as ctune                        # noqa: E402
from nhbot.castle_front import FrontDoor                      # noqa: E402
from nhbot.castle_logic import to_bot, to_map                 # noqa: E402
from nhbot.glyph import SS                                    # noqa: E402
from nhbot.level import Level                                 # noqa: E402
from nle.nethack import actions as A                          # noqa: E402

H, W = 21, 79
CASTLE_KEY = (0, 27)
SOLDIER = nh.GLYPH_MON_OFF + 1
PET = nh.GLYPH_PET_OFF + 5
EEL = nh.GLYPH_MON_OFF + 2


class Perm:
    def __init__(self, name):
        self.mname = name


class BL:
    def __init__(self, pos, hp=50, maxhp=50, time=10000):
        self.y, self.x = (int(v) for v in to_bot(*pos))
        self.hitpoints, self.max_hitpoints, self.time = hp, maxhp, time


class FakeItem:
    def __init__(self, names, letter, glyph=1000, category=nh.TOOL_CLASS, text=None):
        if isinstance(names, str):
            names = [names]
        self.objs = [O.from_name(n) for n in names]
        self.object = self.objs[0]
        self.letter = letter
        self.category = category
        self.text = text or f'a {names[0]}'
        self.glyphs = [glyph]
        self.comment = ''

    def is_unambiguous(self):
        return len(self.objs) == 1


class Items(list):
    def get_letter(self, item):
        return item.letter


class Inv:
    def __init__(self):
        self.items = Items()
        self.engraving_below_me = ''


class Prop:
    def __init__(self):
        self.blind = self.polymorph = self.confusion = self.stun = self.hallu = False


class Char:
    def __init__(self):
        self.prop = Prop()


class Lvl:
    dungeon_number = Level.DUNGEONS_OF_DOOM

    def __init__(self):
        self.objects = np.full((H, W), SS.S_room, dtype=np.int32)
        self.walkable = np.ones((H, W), dtype=bool)

    def key(self):
        return CASTLE_KEY


class Tracker:
    def __init__(self):
        self.monster_mask = np.zeros((H, W), bool)
        self.peaceful_monster_mask = np.zeros((H, W), bool)


class Game:
    """The prompts of apply -> instrument (music.c do_play_instrument) and the drawbridge's answers."""

    def __init__(self, agent, tune='CAFEB', instrument='wooden flute', known=False, plenty=False, deaf=False):
        self.agent = agent
        self.tune = tune
        self.instrument = instrument
        self.known = known
        self.plenty = plenty
        self.deaf = deaf
        self.state = None
        self.buf = ''
        self.played = []

    def respond(self, action):
        a = self.agent
        a.misc = [0, 0, 0]
        if action == A.Command.APPLY:
            self.state = 'apply'
            return 'What do you want to use or apply? [f or ?*]'
        if self.state == 'apply':
            if self.plenty:
                self.state = None
                return 'You feel ... some food spills out.'
            impaired = a.character.prop.confusion or a.character.prop.stun or a.character.prop.hallu
            if impaired:
                self.state = None
                return 'You generate a raucous noise.'
            self.state = 'improv'
            a.misc = [1, 0, 0]
            return 'Improvise? [ynq] (q)'
        if self.state == 'improv' and action == 'n':
            if self.known:
                self.state = 'pt'
                a.misc = [1, 0, 0]
                return 'Play the passtune? [ynq] (q)'
            self.state = 'getlin'
            self.buf = ''
            a.misc = [0, 1, 0]
            return 'What tune are you playing? [5 notes, A-G]'
        if self.state == 'pt' and action == 'y':
            return self._play(self.tune)
        if self.state == 'getlin':
            if action == '\r':
                return self._play(self.buf.upper())
            self.buf += action
            a.misc = [0, 1, 0]
            return f'What tune are you playing? [5 notes, A-G] {self.buf}'
        if action == A.Command.ESC:
            self.state = None
            return 'Never mind.'
        self.state = None
        return ''

    def _play(self, buf):
        self.state = None
        self.played.append(buf)
        a = self.agent
        out = 'You extract a strange sound from the wooden flute!' if not self.deaf else \
            'You can feel the wooden flute emitting vibrations.'
        pos = to_map(a.blstats.y, a.blstats.x)
        near = ctune.bridge_adjacent(pos)
        if buf == self.tune:
            if near:
                self.known = True
                y, x = to_bot(*ctune.SPAN)
                up = a.span_state == 'up'
                a.span_state = 'down' if up else 'up'
                g = SS.S_vodbridge if up else SS.S_vcdbridge
                if a.glyphs[y, x] in (SS.S_vodbridge, SS.S_vcdbridge):
                    a.glyphs[y, x] = g
                a.level.objects[y, x] = g
                out += '  You see a drawbridge ' + ('coming down!' if up else 'coming up!')
            return out
        if self.deaf or not near:
            return out
        gears, tumblers = ctune.feedback(buf, self.tune)
        if tumblers:
            if gears:
                out += f'  You hear {tumblers} tumbler{"s" if tumblers != 1 else ""} click and {gears} gear' \
                       f'{"s" if gears != 1 else ""} turn.'
            else:
                out += f'  You hear {tumblers} tumbler{"s" if tumblers != 1 else ""} click.'
        elif gears:
            out += f'  You hear {gears} gear{"s" if gears != 1 else ""} turn.'
        return out


class FakeAgent:
    def __init__(self, pos, hp=50, maxhp=50):
        self.blstats = BL(pos, hp, maxhp)
        self.step_count = 1000
        self.glyphs = np.full((H, W), SS.S_room, dtype=np.int32)
        self.level = Lvl()
        self.inventory = Inv()
        self.character = Char()
        self.monster_tracker = Tracker()
        self.monsters = []          # (dist, y, x, Perm, glyph)
        self.logs = []
        self.moves = []
        self.steps = []
        self.message = ''
        self.single_message = ''
        self.misc = [0, 0, 0]
        self.game = None
        self.span_state = 'up'
        self.engrave_ok = True
        y, x = to_bot(*ctune.SPAN)
        self.glyphs[y, x] = SS.S_vcdbridge
        self.level.objects[y, x] = SS.S_vcdbridge
        for p in ((5, 7), (5, 9), (5, 6), (5, 10)):
            yy, xx = to_bot(*p)
            self.level.objects[yy, xx] = SS.S_pool
            self.level.walkable[yy, xx] = False

    @property
    def _observation(self):
        return {'misc': self.misc}

    def current_level(self):
        return self.level

    def log(self, msg):
        self.logs.append(msg)

    def get_visible_monsters(self):
        return list(self.monsters)

    @contextlib.contextmanager
    def atom_operation(self):
        yield

    def step(self, action, gen=None, _chain=False):
        self.steps.append(action)
        self.step_count += 1
        msg = self.game.respond(action) if self.game is not None else ''
        self.single_message = msg
        self.message = (self.message + ' ' + msg) if _chain else msg
        if self.game is not None and self.game.state is None and msg and 'strange sound' in msg or \
                (self.game is not None and 'feel' in msg):
            self.blstats.time += 1
        if gen is not None:
            try:
                nxt = next(gen)
            except StopIteration:
                return
            self.step(nxt, gen, _chain=True)

    def search(self, n=1):
        self.steps.append('search')
        self.step_count += 1
        self.blstats.time += n

    def calc_direction(self, y0, x0, y1, x1):
        dy, dx = int(np.sign(y1 - y0)), int(np.sign(x1 - x0))
        return {(-1, 0): 'n', (1, 0): 's', (0, 1): 'e', (0, -1): 'w', (-1, 1): 'ne', (-1, -1): 'nw',
                (1, 1): 'se', (1, -1): 'sw'}[(dy, dx)]

    def direction(self, d):
        self.moves.append(d)
        self.step_count += 1
        self.blstats.time += 1
        dy, dx = {'n': (-1, 0), 's': (1, 0), 'e': (0, 1), 'w': (0, -1), 'ne': (-1, 1), 'nw': (-1, -1),
                  'se': (1, 1), 'sw': (1, -1)}[d]
        if self.steps and self.steps[-1] == A.Command.FIGHT:
            return
        self.blstats.y += dy
        self.blstats.x += dx
        self.inventory.engraving_below_me = ''

    def can_engrave(self):
        return self.engrave_ok

    def engrave(self, text):
        self.steps.append(('engrave', text))
        self.step_count += 1
        self.blstats.time += 1
        self.inventory.engraving_below_me = text
        return True


class FakeCastle:
    def __init__(self, agent):
        self.agent = agent
        self.castle_key = CASTLE_KEY
        self.approached = []
        self.is_active = True

    def active(self):
        return self.is_active

    def committed(self):
        return False

    def _approach(self, spot):
        self.approached.append(spot)
        return True

    def _monster_at(self, mx, my):
        y, x = to_bot(mx, my)
        return nh.glyph_is_monster(int(self.agent.glyphs[y, x]))


class FakeDive:
    def __init__(self, agent):
        self.agent = agent
        self.castle = FakeCastle(agent)
        self.front = FrontDoor(self)
        self.tune = ctune.PassTune(self)

    def _melee_ignores_elbereth(self, mon):
        return getattr(mon, 'mname', '') in ('soldier', 'sergeant', 'lieutenant', 'minotaur')

    def _ignores_elbereth(self, mon):
        return self._melee_ignores_elbereth(mon)


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


def setup(pos=(4, 7), tune='CAFEB', items=('wooden flute',), **game_kw):
    agent = FakeAgent(pos)
    for i, name in enumerate(items):
        agent.inventory.items.append(FakeItem(name, 'fghij'[i], glyph=2000 + i))
    agent.game = Game(agent, tune=tune, **game_kw)
    dive = FakeDive(agent)
    return agent, dive, dive.tune


def put_monster(agent, p, name='soldier', glyph=SOLDIER):
    y, x = to_bot(*p)
    agent.glyphs[y, x] = glyph
    agent.monster_tracker.monster_mask[y, x] = True
    agent.monsters.append((1, y, x, Perm(name), glyph))


def clear_monsters(agent):
    for _, y, x, _, _ in agent.monsters:
        agent.glyphs[y, x] = agent.level.objects[y, x]
        agent.monster_tracker.monster_mask[y, x] = False
    agent.monsters = []


# ---------------------------------------------------------------- pure parts
def test_flag_default_off():
    assert jf_config.CASTLE_PASSTUNE is False
    agent, dive, tune = setup()
    assert tune.active() is False
    assert dive.front._tune_open() is False and dive.front._v3() is jf_config.FRONT_V3
    with flags(CASTLE_PASSTUNE=True):
        assert tune.active() is True


def test_feedback_is_music_c():
    assert ctune.feedback('ABCDE', 'ABCDE') == (5, 0)
    assert ctune.feedback('EDCBA', 'ABCDE') == (1, 4)
    assert ctune.feedback('AAAAA', 'ABCDE') == (1, 0)      # matched[0] by the gear: no tumbler for the other As
    assert ctune.feedback('BAAAA', 'ABCDE') == (0, 2)
    assert ctune.feedback('GGGGG', 'ABCDE') == (0, 0)
    assert ctune.feedback('AABBC', 'BBAAC') == (1, 4)
    rng = random.Random(3)
    tunes = [''.join(rng.choice('ABCDEFG') for _ in range(5)) for _ in range(300)]
    arr = np.array([ctune.from_notes(t) for t in tunes])
    for _ in range(20):
        g = ''.join(rng.choice('ABCDEFG') for _ in range(5))
        vec = ctune._feedback_many(ctune.from_notes(g), arr)
        for t, v in zip(tunes, vec):
            gears, tumb = ctune.feedback(g, t)
            assert v == gears * 6 + tumb, (g, t)


def _solve(secret):
    m = ctune.Mastermind()
    seq = []
    for k in range(1, 20):
        g = m.next_guess()
        seq.append(g)
        if g == secret:
            return k, seq
        gears, tumb = ctune.feedback(g, secret)
        assert m.feed(g, gears, tumb) > 0
    raise AssertionError(secret)


def test_solver_bounded_and_deterministic():
    rng = random.Random(7)
    counts = []
    for _ in range(40):
        secret = ''.join(rng.choice('ABCDEFG') for _ in range(5))
        k, seq = _solve(secret)
        counts.append(k)
        ctune._NEXT_CACHE.clear()
        assert _solve(secret)[1] == seq             # same guesses with a cold cache
    assert max(counts) <= 8 and sum(counts) / len(counts) < 6.0, counts


def test_parse_play():
    p = ctune.parse_play
    s = 'You extract a strange sound from the wooden flute!'
    assert p(s + '  You hear 2 tumblers click and 1 gear turn.') == dict(kind='hint', gears=1, tumblers=2)
    assert p(s + '  You hear 1 tumbler click.') == dict(kind='hint', gears=0, tumblers=1)
    assert p(s + '  You hear 3 gears turn.') == dict(kind='hint', gears=3, tumblers=0)
    assert p(s) == dict(kind='hint', gears=0, tumblers=0)                 # silence: 0/0
    assert p(s + '  You see a drawbridge coming down!')['kind'] == 'opened'
    assert p(s + '  You hear gears turning and chains rattling.')['kind'] == 'opened'
    assert p(s + '  You see a drawbridge going up!')['kind'] == 'closed'
    assert p(s + '  You hear chains rattling and gears turning.')['kind'] == 'closed'
    assert p('You can feel the wooden flute emitting vibrations.')['kind'] == 'deaf'
    assert p('You are incapable of playing the wooden flute.')['kind'] == 'incapable'
    assert p('You generate a raucous noise.  The flute toots.')['kind'] == 'none'


def test_adjacency():
    for p in ((4, 7), (4, 8), (4, 9), (5, 7), (7, 8), (6, 9)):
        assert ctune.bridge_adjacent(p), p
    for p in ((3, 8), (4, 6), (4, 10), (2, 8), (8, 8)):
        assert not ctune.bridge_adjacent(p), p
    # the shore squares the lane plays from are exactly the west ones in that 3x3
    from nhbot.castle_logic import map_char
    shore = {(x, y) for x in range(-1, 5) for y in range(4, 13) if map_char(x, y) == '.' and ctune.bridge_adjacent((x, y))}
    assert shore == set(ctune.TUNE_SPOTS)


def test_instrument_choice():
    rank = ctune.instrument_rank
    assert rank(FakeItem('wooden flute', 'a')) == 0
    assert rank(FakeItem(['wooden harp', 'magic harp'], 'a')) == 0
    assert rank(FakeItem('bugle', 'a')) == 0
    assert rank(FakeItem('frost horn', 'a')) == 1
    assert rank(FakeItem(['tooled horn', 'frost horn', 'fire horn', 'horn of plenty'], 'a')) == 2
    assert rank(FakeItem('horn of plenty', 'a')) is None
    assert rank(FakeItem('leather drum', 'a')) is None
    assert rank(FakeItem('wooden flute', 'a', text='an unpaid wooden flute')) is None
    agent, dive, tune = setup(items=(['tooled horn', 'frost horn', 'fire horn', 'horn of plenty'], 'magic harp'))
    assert tune.instrument().letter == 'g'
    agent, dive, tune = setup(items=('horn of plenty', 'leather drum'))
    assert tune.instrument() is None
    with flags(CASTLE_PASSTUNE=True):
        assert tune.active() is False


# ---------------------------------------------------------------- the prompt sequence
def test_prompt_sequence_first_play():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup(tune='GFEDC')
        agent.inventory.engraving_below_me = 'Elbereth'
        assert tune._step() is True
        assert agent.steps == [A.Command.APPLY, 'f', 'n', 'A', 'A', 'B', 'C', 'D', '\r'], agent.steps
        assert agent.game.played == ['AABCD']
        assert tune.solver.history and tune.solver.history[0][0] == 'AABCD'


def test_known_tune_prompt_answered_y():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup(tune='GFEDC', known=True)
        agent.inventory.engraving_below_me = 'Elbereth'
        tune.tune = 'GFEDC'
        res = tune._play_tune()
        assert agent.steps == [A.Command.APPLY, 'f', 'n', 'y'], agent.steps
        assert res['kind'] == 'opened' and tune.bridge() == 'down'


def test_horn_of_plenty_marked_bad():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup(items=(['tooled horn', 'horn of plenty'],), plenty=True)
        agent.inventory.engraving_below_me = 'Elbereth'
        assert tune._step() is False and tune.done and 'no tune played' in tune.reason
        assert 2000 in tune.bad and tune.instrument() is None and tune.plays == 0


# ---------------------------------------------------------------- the whole search, the crusher, the hand-over
def test_full_solve_then_crusher_and_handoff():
    with flags(CASTLE_PASSTUNE=True, FRONT_DOOR=False, FRONT_V3=False):
        agent, dive, tune = setup(pos=(3, 8), tune='DGABE')
        assert tune.active()
        n = 0
        while tune.tune is None and n < 30:
            assert tune._step() is True
            n += 1
        assert tune.tune == 'DGABE' and agent.span_state == 'down' and tune.bridge() == 'down'
        assert ('engrave', 'Elbereth') in agent.steps and tune._pos() in ctune.TUNE_SPOTS
        assert len(agent.game.played) <= 8
        # a soldier steps onto the lowered span: raise it on him
        put_monster(agent, ctune.SPAN)
        assert tune._step() is True
        assert agent.span_state == 'up' and tune.cycles == 1
        clear_monsters(agent)
        # ... then lower it again
        assert tune._step() is True and agent.span_state == 'down'
        # nothing comes: after PT_CRUSH_WAIT turns the front door gets the castle
        r = True
        for _ in range(jf_config.PT_CRUSH_WAIT + 5):
            r = tune._step()
            if not r:
                break
        assert r is False and tune.handed_off and not tune.active()
        assert dive.front._tune_open() and dive.front._v3()
        # the front door takes it from here although FRONT_DOOR is off and the passage plan is still active
        dive.castle.is_active = True
        assert dive.front.active()
    # flag off: the same hand-over state means nothing to the front door
    assert not dive.front._tune_open() and not dive.front.active()


def test_pet_on_span_blocks_the_raise():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup(tune='DGABE')
        agent.inventory.engraving_below_me = 'Elbereth'
        tune.tune = 'DGABE'
        agent.game.known = True
        tune._play_tune()                       # bridge down
        assert agent.span_state == 'down'
        y, x = to_bot(*ctune.SPAN)
        agent.glyphs[y, x] = PET
        put_monster(agent, ctune.PORTCULLIS)
        assert tune._step() is True
        assert agent.span_state == 'down' and agent.steps[-1] == 'search'


def test_low_hp_raises_and_rests():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup(tune='DGABE')
        agent.inventory.engraving_below_me = 'Elbereth'
        tune.tune = 'DGABE'
        agent.game.known = True
        tune._play_tune()
        agent.blstats.hitpoints = 25            # 0.5 < PT_REST_HP
        assert tune._step() is True and agent.span_state == 'up' and tune.resting
        assert tune._step() is True and agent.steps[-1] == 'search'
        agent.blstats.hitpoints = 45
        assert tune._step() is True and agent.span_state == 'down'


# ---------------------------------------------------------------- aborts
def test_abort_low_hp_with_bridge_down_raises_first():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup(tune='DGABE')
        agent.inventory.engraving_below_me = 'Elbereth'
        tune.tune = 'DGABE'
        agent.game.known = True
        tune._play_tune()
        agent.blstats.hitpoints = 10
        assert tune._step() is False
        assert tune.done and 'low HP' in tune.reason and agent.span_state == 'up'


def test_low_hp_while_searching_pauses():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup()
        agent.blstats.hitpoints = 10
        assert tune._step() is False and not tune.done and tune.paused
        assert not tune.active()
        agent.blstats.hitpoints = 45
        assert tune.active()


def test_abort_eel_without_elbereth():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup()
        agent.engrave_ok = False
        put_monster(agent, (5, 7), 'giant eel', EEL)
        assert tune._step() is False and tune.done and 'sea monster' in tune.reason
        assert A.Command.APPLY not in agent.steps
    # on Elbereth the eel is no reason to stop
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup()
        agent.inventory.engraving_below_me = 'Elbereth'
        put_monster(agent, (5, 7), 'giant eel', EEL)
        assert tune._step() is True and not tune.done and A.Command.APPLY in agent.steps


def test_abort_held():
    # (the pre-PT_V2 lane; PT_V2's Elbereth escape: tests/test_castle_lane_v2.py)
    with flags(CASTLE_PASSTUNE=True, PT_V2=False):
        agent, dive, tune = setup()
        agent.inventory.engraving_below_me = 'Elbereth'
        agent.message = 'The giant eel swings itself around you!'
        assert tune._step() is False and tune.done and 'held' in tune.reason


def test_abort_too_many_monsters():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup()
        agent.inventory.engraving_below_me = 'Elbereth'
        for p in ((3, 6), (3, 7), (3, 8)):
            put_monster(agent, p, 'hill orc')
        assert tune._step() is False and tune.done and 'hostiles' in tune.reason
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup()
        put_monster(agent, (3, 7), 'minotaur')
        assert tune._step() is False and 'minotaur' in tune.reason


def test_soldier_next_to_us_is_fought():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup()
        agent.inventory.engraving_below_me = 'Elbereth'
        put_monster(agent, (3, 7))
        assert tune._step() is True and agent.steps[-1] == A.Command.FIGHT and agent.moves[-1] == 'w'


def test_impaired_waits_never_improvises():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup()
        agent.inventory.engraving_below_me = 'Elbereth'
        agent.character.prop.confusion = True
        for _ in range(jf_config.PT_IMPAIRED_WAIT):
            assert tune._step() is True
        assert A.Command.APPLY not in agent.steps
        assert tune._step() is False and tune.done


def test_deaf_aborts():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup(deaf=True)
        agent.inventory.engraving_below_me = 'Elbereth'
        assert tune._step() is False and tune.done and 'deaf' in tune.reason


def test_not_on_west_side_or_polymorphed():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup(pos=(30, 8))
        assert not tune.active()
        agent, dive, tune = setup(pos=(-3, 9))
        assert tune.active()
        agent.character.prop.polymorph = True
        assert not tune.active()


def test_walks_to_a_tune_spot_avoiding_eels():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = setup(pos=(3, 8))
        put_monster(agent, (5, 6), 'giant eel', EEL)      # next to (04,07) only
        assert tune._step() is True
        assert tune.spot == (4, 9) and agent.moves == ['se']


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} tests passed')
