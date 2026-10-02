"""CASTLE_PASSTUNE (passtune lane): learn the castle's drawbridge tune by Mastermind on a tonal instrument, use the
bridge as a crusher, then lower it and hand over to the front door's walk in (castle_front.py FRONT_V3 path: the
maze-mouth hold, row 08, the throne room, the corner towers' chest -- CASTLE_WISH_FIRST).

NetHack 3.6.6 (NLE 1.3.0 src/music.c, dbridge.c; research/castle_entry.md):

* music.c do_play_instrument(): any instrument but a drum asks 'Improvise?' (ynq) unless stunned, confused or
  hallucinating -- then it improvises at once, and a charged frost/fire horn asks a direction and fires its ray. 'n'
  goes to the tune: once the tune is fully known (u.uevent.uheard_tune == 2) 'Play the passtune?' (ynq; 'y' plays it),
  else getlin 'What tune are you playing? [5 notes, A-G]'. The passtune path never reaches do_improvisation: no
  instrument effect at all (no ray, no scare, no sleep, no charge used), and no noise that wakes anything.
  Wind instruments (flutes, horns, bugle) need can_blow(): 'You are incapable of playing ...'.
  Then 'You extract a strange sound from <the instrument>!' ('You can feel <it> emitting vibrations.' when Deaf).
* The right tune with the drawbridge span or its wall in the 3x3 around us toggles the bridge (open_drawbridge:
  'You see a drawbridge going/coming down!' or 'You hear gears turning and chains rattling.'; close_drawbridge:
  'You see a drawbridge coming/going up!' or 'You hear chains rattling and gears turning.').
* A wrong tune, not Deaf, with IS_DRAWBRIDGE or the drawbridge wall in that 3x3 gives Mastermind feedback:
  'You hear N tumbler(s) click and M gear(s) turn.' / 'You hear N tumbler(s) click.' / 'You hear M gear(s) turn.',
  and nothing at all for 0/0. Gears are right notes in the right place; a tumbler is a note matched (once) to an
  unmatched place y of the tune where the guess is itself wrong (buf[y] != tune[y]): feedback() below.
* castle.des DRAWBRIDGE:(05,08),east: the span is (05,08), its wall (the portcullis) (06,08); the only shore squares
  in a 3x3 with either are (04,07), (04,08), (04,09), each beside 3 moat squares (the giant eels start at (05,07)
  and (05,09), asleep 4 in 5, and respect Elbereth). 7^5 tunes (dungeon.c).
* dbridge.c close_drawbridge(): a non-flier on the span is crushed or drowned, one in the portcullis crushed 80%
  (the rest land on the span and die there); xkilled: we get the experience. Our square's engraving is untouched.
"""

import collections
import itertools
import re

import nle.nethack as nh
import numpy as np
from nle.nethack import actions as A

from . import jf_config
from . import objects as O
from .castle_logic import WEST_COURTYARD, map_char, to_bot, to_map
from .glyph import SS
from .strategy import Strategy

SPAN = (5, 8)
PORTCULLIS = (6, 8)
APPROACH = (3, 8)                  # a courtyard square with no water beside it, next to every tune spot
TUNE_SPOTS = ((4, 7), (4, 9), (4, 8))   # shore squares with the span in their 3x3; (04,08) borders both eels
BRIDGE_UP = frozenset({SS.S_vcdbridge, SS.S_hcdbridge})
BRIDGE_DOWN = frozenset({SS.S_vodbridge, SS.S_hodbridge})
NOTES = 'ABCDEFG'

_TONAL_NAMES = ('wooden flute', 'magic flute', 'tooled horn', 'frost horn', 'fire horn', 'wooden harp',
                'magic harp', 'bugle')
TONAL = frozenset(O.from_name(n) for n in _TONAL_NAMES)
QUIET = frozenset(O.from_name(n) for n in ('wooden flute', 'magic flute', 'wooden harp', 'magic harp', 'bugle'))
PLENTY = O.from_name('horn of plenty')

_RE_BOTH = re.compile(r'You hear (\d+) tumblers? click and (\d+) gears? turn')
_RE_TUMB = re.compile(r'You hear (\d+) tumblers? click\.')
_RE_GEAR = re.compile(r'You hear (\d+) gears? turn\.')
_OPENED = ('drawbridge coming down', 'drawbridge going down', 'gears turning and chains rattling')
_CLOSED = ('drawbridge coming up', 'drawbridge going up', 'chains rattling and gears turning')


# ------------------------------------------------------------------------------------------------ the tune (pure)

def feedback(guess, tune):
    """music.c's hint for `guess` against `tune` (strings or 5-sequences): (gears, tumblers)."""
    matched = [False] * 5
    gears = tumblers = 0
    for x in range(5):
        if guess[x] == tune[x]:
            gears += 1
            matched[x] = True
        else:
            for y in range(5):
                if not matched[y] and guess[x] == tune[y] and guess[y] != tune[y]:
                    tumblers += 1
                    matched[y] = True
                    break
    return gears, tumblers


def _feedback_many(guess, tunes):
    """feedback() vectorised over an (n, 5) array of tunes: gears * 6 + tumblers."""
    n = len(tunes)
    matched = np.zeros((n, 5), bool)
    gears = np.zeros(n, np.int16)
    tumb = np.zeros(n, np.int16)
    for x in range(5):
        g = tunes[:, x] == guess[x]
        gears += g
        matched[g, x] = True
        todo = ~g
        for y in range(5):
            hit = todo & ~matched[:, y] & (tunes[:, y] == guess[x]) & (guess[y] != tunes[:, y])
            tumb += hit
            matched[hit, y] = True
            todo &= ~hit
    return gears * 6 + tumb


_CODES = None
_NEXT_CACHE = {}       # history (tuple of (guess, code)) -> next guess: the solver is deterministic


def _codes():
    global _CODES
    if _CODES is None:
        _CODES = np.array(list(itertools.product(range(7), repeat=5)), dtype=np.int8)
    return _CODES


def to_notes(code):
    return ''.join(NOTES[int(v)] for v in code)


def from_notes(s):
    return np.array([NOTES.index(c) for c in s.upper()], dtype=np.int8)


class Mastermind:
    """Consistent-guess solver (research/castle_entry/mastermind.py, made deterministic): the first guess AABCD,
    then among (an evenly spaced sample of at most POOL of) the tunes still consistent with every hint, the one whose
    hint partition of them has the smallest sum of squares. ~5.2 plays on average, at most 7-8."""
    POOL = 60
    FIRST = (0, 0, 1, 2, 3)

    def __init__(self):
        self.cand = _codes()
        self.history = []

    def remaining(self):
        return len(self.cand)

    def next_guess(self):
        key = tuple(self.history)
        if key in _NEXT_CACHE:
            return _NEXT_CACHE[key]
        if not self.history:
            g = to_notes(self.FIRST)
        elif len(self.cand) <= 2:
            g = to_notes(self.cand[0])
        else:
            cand = self.cand
            if len(cand) > self.POOL:
                idx = np.unique(np.linspace(0, len(cand) - 1, self.POOL).round().astype(int))
                pool = cand[idx]
            else:
                pool = cand
            best, best_score = None, None
            for gg in pool:
                sizes = np.bincount(_feedback_many(gg, cand), minlength=36).astype(np.int64)
                score = int((sizes * sizes).sum())
                if best_score is None or score < best_score:
                    best, best_score = gg, score
            g = to_notes(best)
        _NEXT_CACHE[key] = g
        return g

    def feed(self, guess, gears, tumblers):
        """A wrong guess's hint; returns how many tunes remain consistent (0: the hints contradict each other)."""
        code = int(gears) * 6 + int(tumblers)
        g = from_notes(guess)
        self.cand = self.cand[_feedback_many(g, self.cand) == code]
        self.history.append((guess, code))
        return len(self.cand)


def parse_play(msg):
    """What one play of the tune said: dict(kind=..., gears, tumblers). kind: 'incapable' (can't blow it), 'deaf'
    (no hints), 'opened' / 'closed' (the right tune toggled the bridge), 'hint' (gears/tumblers, 0/0 = silence
    after a strange sound), 'none' (no tune was played: no 'strange sound' -- an improvisation, a horn of plenty)."""
    msg = msg or ''
    out = dict(kind='none', gears=0, tumblers=0)
    if 'You are incapable of playing' in msg:
        out['kind'] = 'incapable'
        return out
    if any(s in msg for s in _OPENED):
        out['kind'] = 'opened'
        return out
    if any(s in msg for s in _CLOSED):
        out['kind'] = 'closed'
        return out
    if 'emitting vibrations' in msg:
        out['kind'] = 'deaf'
        return out
    m = _RE_BOTH.search(msg)
    if m:
        out.update(kind='hint', tumblers=int(m.group(1)), gears=int(m.group(2)))
        return out
    m = _RE_TUMB.search(msg)
    if m:
        out.update(kind='hint', tumblers=int(m.group(1)))
        return out
    m = _RE_GEAR.search(msg)
    if m:
        out.update(kind='hint', gears=int(m.group(1)))
        return out
    if 'extract a strange sound' in msg:
        out['kind'] = 'hint'   # silence: no note of the guess is in the tune
    return out


def bridge_adjacent(p):
    """music.c: the drawbridge span or its wall in the 3x3 around map square p."""
    return any(max(abs(p[0] - q[0]), abs(p[1] - q[1])) <= 1 for q in (SPAN, PORTCULLIS))


def instrument_rank(item):
    """0: a flute, harp or bugle (known or not); 1: a horn known to be tonal; 2: an unknown horn (a horn of plenty
    2 times in 11); None: no use for the tune (drums, horn of plenty, anything else)."""
    if item.category != nh.TOOL_CLASS or not item.objs or 'unpaid' in (item.text or ''):
        return None
    objs = set(item.objs)
    if objs <= QUIET:
        return 0
    if objs <= TONAL:
        return 1
    if objs <= TONAL | {PLENTY} and objs != {PLENTY}:
        return 2
    return None


# ------------------------------------------------------------------------------------------------ the lane

class PassTune:
    def __init__(self, dive):
        self.dive = dive
        self.agent = dive.agent
        self.done = False
        self.reason = None
        self.solver = None
        self.tune = None             # the passtune (notes) once the bridge answered it
        self.handed_off = False
        self.tries = collections.Counter()
        self.bad = set()             # instrument glyphs that played no tune (a horn of plenty, can't blow it)
        self.plays = 0               # tune-search plays
        self.cycles = 0              # crusher raises
        self.crush_start = None      # turn the crusher began
        self.down_since = None       # turn the bridge last went down in the crusher
        self.crusher_over = False
        self.resting = False
        self.paused = 0
        self.steps = 0
        self.logged = set()
        self.spot = None
        self._bstate = None          # 'up' / 'down' from our own plays' messages
        self._state = None

    # ---------------------------------------------------------------- helpers

    def _log(self, msg):
        self.agent.log(f'TUNE {msg}')

    def _mile(self, name, extra=''):
        if name in self.logged:
            return
        self.logged.add(name)
        bl = self.agent.blstats
        self._log(f'M:{name} turn {bl.time} hp {bl.hitpoints}/{bl.max_hitpoints} pos {self._pos()} {extra}'.rstrip())

    def _set_state(self, state):
        if state != self._state:
            self._state = state
            self._log(f'{state} (pos {self._pos()}, turn {self.agent.blstats.time})')

    def _pos(self):
        bl = self.agent.blstats
        return tuple(int(v) for v in to_map(bl.y, bl.x))

    def _hp_frac(self):
        bl = self.agent.blstats
        return bl.hitpoints / max(1, bl.max_hitpoints)

    def _front(self):
        return self.dive.front

    def _glyph(self, p):
        y, x = to_bot(*p)
        return int(self.agent.glyphs[y, x])

    def _sym(self, p):
        y, x = to_bot(*p)
        objs = self.agent.current_level().objects
        if not (0 <= y < objs.shape[0] and 0 <= x < objs.shape[1]):
            return None
        return int(objs[y, x])

    def bridge(self):
        """'up', 'down' or None: the span's glyph when it shows, else what our last toggle said, else the map."""
        g = self._glyph(SPAN)
        if g in BRIDGE_UP:
            return 'up'
        if g in BRIDGE_DOWN:
            return 'down'
        if self._bstate is not None:
            return self._bstate
        s = self._sym(SPAN)
        if s in BRIDGE_UP:
            return 'up'
        if s in BRIDGE_DOWN:
            return 'down'
        return None

    def _destroyed(self):
        """A striking bolt / force bolt broke it (dbridge.c destroy_drawbridge): moat (or floor) and an empty
        doorway -- no tune works any more."""
        return self.bridge() is None and self._sym(PORTCULLIS) == SS.S_ndoor and \
            self._sym(SPAN) in (SS.S_pool, SS.S_water, SS.S_room, SS.S_ice)

    def instrument(self):
        best = None
        for it in self.agent.inventory.items:
            r = instrument_rank(it)
            if r is None:
                continue
            g = it.glyphs[0] if it.glyphs else None
            if g in self.bad:
                continue
            if r == 2:
                st = getattr(self.agent, '_opp', None)   # opp_items: what blowing this horn did (HORN_SCARE)
                if st is not None and st.horn_glyphs.get(g) == 'plenty':
                    continue
            if best is None or r < best[0]:
                best = (r, it)
        return None if best is None else best[1]

    def _engraved(self):
        return (self.agent.inventory.engraving_below_me or '').lower() == 'elbereth'

    def _can_write(self):
        return self.agent.can_engrave() and not self.agent.character.prop.blind

    def _monsters(self):
        """Visible hostiles (not pets): (map pos, permonst, glyph)."""
        out = []
        for m in self.agent.get_visible_monsters():
            if nh.glyph_is_pet(int(m[4])):
                continue
            out.append((tuple(int(v) for v in to_map(m[1], m[2])), m[3], int(m[4])))
        return out

    def _is_sea(self, p):
        """A monster at p swims: the moat, or the span while it is raised (the moat under it)."""
        if p == SPAN:
            return self.bridge() != 'down'
        return map_char(*p) == '}'

    def _adjacent(self, p):
        me = self._pos()
        return max(abs(p[0] - me[0]), abs(p[1] - me[1])) == 1

    def _sea_adjacent(self):
        return [m for m in self._monsters() if self._adjacent(m[0]) and self._is_sea(m[0])]

    def _land_adjacent(self):
        """Adjacent hostiles on land; the span and the portcullis don't count while the crusher can take them."""
        down = self.bridge() == 'down'
        out = []
        for p, mon, g in self._monsters():
            if not self._adjacent(p) or self._is_sea(p):
                continue
            if down and self.tune is not None and p in (SPAN, PORTCULLIS):
                continue
            out.append((p, mon, g))
        return out

    def _ignores(self, mon):
        return self.dive._melee_ignores_elbereth(mon)

    def _victims(self):
        """(hostiles, blockers) on the span or in the portcullis: blockers are our pets and peacefuls (no crushing
        them: -15 alignment / murder), seen by glyph and the tracker's peaceful mask."""
        hostiles, blockers = [], []
        tracker = self.agent.monster_tracker
        for p in (SPAN, PORTCULLIS):
            y, x = to_bot(*p)
            g = int(self.agent.glyphs[y, x])
            if nh.glyph_is_pet(g) or (tracker.peaceful_monster_mask[y, x] and
                                      (nh.glyph_is_monster(g) or tracker.monster_mask[y, x])):
                blockers.append(p)
            elif nh.glyph_is_monster(g) or g == nh.GLYPH_INVISIBLE or tracker.monster_mask[y, x]:
                hostiles.append(p)
        return hostiles, blockers

    # ---------------------------------------------------------------- eligibility

    def active(self):
        if not jf_config.CASTLE_PASSTUNE or self.done:
            return False
        front = self._front()
        if front is None or not front.on_castle():
            return False
        agent = self.agent
        if agent.character.prop.polymorph:
            return False
        pos = self._pos()
        if not (pos[0] < 0 or pos in WEST_COURTYARD):
            return False   # the west side only (a xorn in a tower, the east courtyard: other lanes)
        if self.dive.castle.committed():
            return False   # a lift crossing under way keeps going
        if self.instrument() is None:
            return False
        if self.handed_off:
            return False   # the front door's walk has the castle now
        if self._destroyed():
            self._abort('the drawbridge is destroyed')
            return False
        if self.paused:
            if self._hp_frac() < jf_config.PT_RESUME_HP:
                return False
            self._log(f'resuming at hp {self._hp_frac():.2f}')
            self.paused = 0
        return True

    def strategy(self):
        def f():
            if not self.active():
                yield False
            yield True
            steps = 0
            while self.active() and steps < 200:
                before = self.agent.step_count
                if not self._step():
                    break
                steps += 1
                if self.agent.step_count == before:
                    self.agent.search()

        return Strategy(f)

    # ---------------------------------------------------------------- the plan

    def _abort(self, why):
        """The lane ends for good: the castle's other lanes (lift, front door, trap doors) as before. With the tune
        known and the bridge down beside us, raise it first (whatever stands on it dies; nothing crosses after)."""
        if self.done:
            return False
        if self.tune is not None and self.bridge() == 'down' and bridge_adjacent(self._pos()) and \
                not self.handed_off and self.tries['abort_raise'] < 1 and self._can_play():
            self.tries['abort_raise'] += 1
            self._log(f'raising the bridge before giving up ({why})')
            try:
                self._play_tune()
            except Exception as e:   # never let the way out fail
                self._log(f'abort raise failed: {e!r}')
        self.done = True
        self.reason = why
        self._mile('abort', why)
        return False

    def _can_play(self):
        prop = self.agent.character.prop
        return not (prop.confusion or prop.stun or prop.hallu or prop.polymorph)

    def _held(self):
        msg = self.agent.message or ''
        if 'swings itself around you' in msg or 'cannot escape from' in msg:
            self._held_turn = self.agent.blstats.time
        t = getattr(self, '_held_turn', None)
        return t is not None and self.agent.blstats.time - t <= 3

    def _danger(self):
        """Why the lane must end now, or None."""
        if self._held():
            return 'held by a sea monster'
        land = self._land_adjacent()
        if len(land) >= jf_config.PT_MAX_ADJACENT:
            return f'{len(land)} hostiles next to us'
        names = [getattr(m[1], 'mname', '?') for m in land]
        if 'minotaur' in names:
            return 'a minotaur next to us'
        if sum(1 for m in land if self._ignores(m[1])) >= 2:
            return f'Elbereth-ignorers next to us: {names}'
        return None

    def _step(self):
        agent = self.agent
        self.steps += 1
        if self.steps > jf_config.PT_MAX_STEPS:
            return self._abort('step budget')
        pos = self._pos()
        inst = self.instrument()
        if inst is None:
            return self._abort('no instrument')
        if 'start' not in self.logged:
            self._mile('start', f'instrument {inst.text if inst else None!r} bridge {self.bridge()}')
        why = self._danger()
        if why:
            return self._abort(why)
        hp = self._hp_frac()
        if hp < jf_config.PT_ABORT_HP:
            if self.tune is None or self.bridge() != 'down':
                # nothing to protect: let the survival layers (Elbereth rest, prayer, retreat) have us; back later
                self.paused += 1
                self.tries['pauses'] += 1
                if self.tries['pauses'] > jf_config.PT_MAX_PAUSES:
                    return self._abort(f'low HP ({hp:.2f}) too often')
                self._log(f'pausing at hp {hp:.2f}')
                return False
            return self._abort(f'low HP {hp:.2f}')
        if not self._can_play() or agent.character.prop.blind:
            self.tries['impaired'] += 1
            if self.tries['impaired'] > jf_config.PT_IMPAIRED_WAIT:
                return self._abort('confused / stunned / hallucinating / blind too long')
            self._set_state('waiting out an impairment')
            agent.search()
            return True
        if not bridge_adjacent(pos):
            return self._go_spot()
        self._mile('spot', f'at {pos}')
        if self.tune is not None and self.bridge() == 'down':
            hostiles, blockers = self._victims()
            if hostiles and not blockers:
                return self._crush_step()   # the ones on the span first: the raise kills them
        land = self._land_adjacent()
        ignorers = [m for m in land if self._ignores(m[1])]
        if ignorers:
            return self._attack(ignorers[0])   # (an @ that stepped off the span: Elbereth doesn't stop it)
        if not self._engraved() and self._can_write() and self.tries['elbereth'] < jf_config.PT_ELBERETH_TRIES:
            self.tries['elbereth'] += 1
            self._set_state('Elbereth on the tune square')
            agent.engrave('Elbereth')
            return True
        if self._sea_adjacent() and not self._engraved():
            return self._abort('a sea monster next to us and no Elbereth under us')
        if land and not self._engraved():
            return self._attack(land[0])
        if self.tune is None:
            return self._solve_step(inst)
        return self._crush_step()

    def _go_spot(self):
        """To a tune square: by the known floor when it leads there, else the castle passage's courtyard approach
        (explores / digs the west maze) to (03,08), next to all three."""
        agent = self.agent
        front = self._front()
        pos = self._pos()
        self.tries['go'] += 1
        if self.tries['go'] > jf_config.PT_GO_BUDGET:
            return self._abort('tune square not reached')
        if self.spot is None or self._monster_on(self.spot):
            self.spot = self._choose_spot()
        if self.spot is None:
            return self._abort('no free tune square')
        path = front._path(pos, self.spot)
        if not path:
            if pos == APPROACH:
                self.tries['blocked'] += 1
                if self.tries['blocked'] > 20:
                    return self._abort('tune squares blocked')
                agent.search()
                return True
            self._set_state(f'approaching {APPROACH}')
            return bool(self.dive.castle._approach(APPROACH))
        n = path[0]
        if self._monster_on(n):
            for m in self._land_adjacent():
                if m[0] == n:
                    return self._attack(m)   # a hostile in the way
            self.tries['blocked'] += 1
            if self.tries['blocked'] > 20:
                return self._abort(f'way to {self.spot} blocked')
            agent.search()
            return True
        self._set_state(f'walking to the tune square {self.spot}')
        y, x = to_bot(*n)
        agent.direction(agent.calc_direction(agent.blstats.y, agent.blstats.x, y, x))
        return True

    def _monster_on(self, p):
        y, x = to_bot(*p)
        if (y, x) == (self.agent.blstats.y, self.agent.blstats.x):
            return False
        g = int(self.agent.glyphs[y, x])
        return bool(nh.glyph_is_monster(g)) or g == nh.GLYPH_INVISIBLE

    def _choose_spot(self):
        """The tune square with the fewest sea monsters seen beside it (then (04,07), (04,09), (04,08))."""
        sea = [m[0] for m in self._monsters() if self._is_sea(m[0])]
        best = None
        for i, p in enumerate(TUNE_SPOTS):
            if self._monster_on(p) or self._front()._boulder(p):
                continue
            n = sum(1 for q in sea if max(abs(q[0] - p[0]), abs(q[1] - p[1])) == 1)
            key = (n, i)
            if best is None or key < best[0]:
                best = (key, p)
        return None if best is None else best[1]

    def _attack(self, m):
        agent = self.agent
        p, mon, _ = m
        y, x = to_bot(*p)
        self.tries['fights'] += 1
        if self.tries['fights'] > jf_config.PT_MAX_FIGHTS:
            return self._abort('too much fighting on the tune square')
        self._set_state(f'fighting {getattr(mon, "mname", "?")} at {p}')
        with agent.atom_operation():
            agent.step(A.Command.FIGHT)
            agent.direction(agent.calc_direction(agent.blstats.y, agent.blstats.x, y, x))
        return True

    # ---- playing

    def _play(self, notes):
        """apply -> the instrument -> 'Improvise?' n -> 'Play the passtune?' y (the game knows it) or 'What tune are
        you playing? [5 notes, A-G]' notes + Enter. Returns (parse_play dict, seen prompts)."""
        agent = self.agent
        item = self.instrument()
        letter = agent.inventory.items.get_letter(item)
        seen = dict(apply=False, improvise=False, passtune=False, typed=False, direction=False)

        def gen():
            if 'What do you want to use or apply?' not in (agent.single_message or ''):
                return
            seen['apply'] = True
            yield letter
            for _ in range(12):
                msg = agent.single_message or ''
                misc = agent._observation['misc']
                if 'Improvise?' in msg and not seen['improvise']:
                    seen['improvise'] = True
                    yield 'n'
                    continue
                if 'Play the passtune?' in msg and not seen['passtune']:
                    seen['passtune'] = True
                    yield 'y'
                    continue
                if 'What tune are you playing?' in msg and not seen['typed']:
                    seen['typed'] = True
                    yield from notes
                    yield '\r'
                    continue
                if 'In what direction?' in msg and not seen['direction']:
                    seen['direction'] = True   # an improvising ray horn (we were impaired after all): no ray
                    yield A.Command.ESC
                    continue
                if misc[2] and not misc[1]:
                    yield ' '
                    continue
                return

        before = self.bridge()
        with agent.atom_operation():
            agent.step(A.Command.APPLY, gen())
        msg = agent.message or ''
        res = parse_play(msg)
        if res['kind'] == 'hint' and before is not None:
            # a toggle whose message we missed shows on the span
            after = self.bridge()
            if before == 'up' and after == 'down':
                res['kind'] = 'opened'
            elif before == 'down' and after == 'up':
                res['kind'] = 'closed'
        if res['kind'] == 'none' and seen['apply'] and not seen['improvise'] and not seen['passtune'] and \
                not seen['typed']:
            g = item.glyphs[0] if item.glyphs else None
            self.bad.add(g)   # no 'Improvise?': not an instrument (a horn of plenty)
        if res['kind'] == 'incapable':
            self.bad.add(item.glyphs[0] if item.glyphs else None)
        if res['kind'] == 'opened':
            self._bstate = 'down'
        elif res['kind'] == 'closed':
            self._bstate = 'up'
        self._log(f'played {notes} on {item.text!r}: {res} prompts {seen} msg {msg[:160]!r}')
        return res, seen

    def _play_tune(self):
        """The known passtune (the game offers it: 'Play the passtune?')."""
        res, seen = self._play(self.tune or 'AAAAA')
        if res['kind'] in ('opened', 'closed'):
            self.tries['toggles'] += 1
        return res

    def _solve_step(self, inst):
        if self.solver is None:
            self.solver = Mastermind()
        self.plays += 1
        if self.plays > jf_config.PT_MAX_PLAYS:
            return self._abort(f'{self.plays - 1} plays without the tune')
        guess = self.solver.next_guess()
        self._set_state('playing for the passtune')
        res, seen = self._play(guess)
        kind = res['kind']
        if kind in ('opened', 'closed'):
            # (with 'Play the passtune?' the game already knew it -- a prayer's 'Hark!' -- and played it for us; every
            # later play answers that prompt too, so the notes are only for the log)
            self.tune = guess
            self._mile('tune', f'{guess} after {self.plays} plays, bridge {kind}'
                               f'{" (the game played it)" if seen["passtune"] else ""}')
            return True
        if kind == 'hint':
            left = self.solver.feed(guess, res['gears'], res['tumblers'])
            self._log(f'hint {guess}: {res["gears"]} gears {res["tumblers"]} tumblers -> {left} tunes left')
            if left == 0:
                return self._abort('the hints contradict each other')
            return True
        if kind == 'deaf':
            return self._abort('deaf: no hints')
        self.plays -= 1   # nothing was played
        self.tries['misplay'] += 1
        if self.tries['misplay'] > 4 or self.instrument() is None:
            return self._abort(f'no tune played ({kind})')
        return True

    # ---- the crusher, then in

    def _crush_step(self):
        agent = self.agent
        now = agent.blstats.time
        b = self.bridge()
        if b is None:
            return self._abort('bridge state unknown')
        if self.crush_start is None:
            self.crush_start = now
            self._mile('crusher', f'bridge {b}')
        over = (not jf_config.PT_CRUSH or self.crusher_over or self.cycles >= jf_config.PT_CRUSH_MAX or
                now - self.crush_start > jf_config.PT_CRUSH_TURNS)
        hp = self._hp_frac()
        if b == 'down':
            hostiles, blockers = self._victims()
            if hostiles and not blockers and not over:
                self.cycles += 1
                self.down_since = None
                self._set_state(f'raising the bridge on {hostiles}')
                res = self._play_tune()
                self._log(f'crush {self.cycles}: {res["kind"]} {agent.message[:200]!r}')
                return True
            if hp < jf_config.PT_REST_HP and not blockers and self.tries['rest_raise'] < 6:
                self.tries['rest_raise'] += 1
                self.resting = True
                self._set_state(f'hurt ({hp:.2f}): raising the bridge to rest')
                self._play_tune()
                return True
            if over:
                return self._handoff()
            if self.down_since is None:
                self.down_since = now
            if now - self.down_since > jf_config.PT_CRUSH_WAIT:
                self.crusher_over = True
                self._log(f'crusher over: nothing came for {now - self.down_since} turns ({self.cycles} raises)')
                return self._handoff()
            self._set_state('bridge down: waiting for the castle to come out')
            agent.search()
            return True
        # the bridge is up
        if self.resting or hp < jf_config.PT_REST_HP:
            self.resting = hp < jf_config.PT_RESUME_HP
            if self.resting:
                self.tries['rest'] += 1
                if self.tries['rest'] > jf_config.PT_REST_TURNS:
                    return self._abort('rested too long')
                self._set_state('resting behind the raised bridge')
                agent.search(3)
                return True
        self._set_state('lowering the bridge')
        res = self._play_tune()
        if res['kind'] == 'opened':
            self.down_since = now
            self._mile('lowered')
        return True

    def _handoff(self):
        if self.bridge() != 'down':
            self.tries['handoff_lower'] += 1
            if self.tries['handoff_lower'] > 3:
                return self._abort('the bridge would not come down for the hand-over')
            self._play_tune()
            return True
        self.handed_off = True
        self._mile('handoff', f'tune {self.tune} raises {self.cycles} plays {self.plays}')
        return False


def strategy(dive):
    tune = getattr(dive, 'tune', None)
    if tune is None:
        return Strategy(lambda: iter([False]))
    return tune.strategy()
