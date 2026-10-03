"""Tourist kit lane (jf_config.TOU_CAMERA, TOU_QUAFF; off by default, role-gated in roles.py OVERRIDES['tou']).

A Tourist starts (u_init.c Tourist[]) with rn1(20,21) = 21-40 +2 darts (quivered, nothing wielded), ~10 random food
items, 2 potions of extra healing, 4 scrolls of magic mapping, a Hawaiian shirt, an expensive camera with rn1(70,30) =
30-99 charges (mkobj.c), a credit card and rnd(1000) gold; low HP and no intrinsics. research/tou_kit.md measured 90
current-code dev games (au_tou_, nhbot byte-identical to v10c):
  * the camera was applied twice in 90 games (both by the minotaur lane at Dlvl 24-25); the 29 Dlvl-20+ inventory dumps
    still held it with 75 charges on average;
  * 22 of the 38 grind deaths (Dlvl-1 grind + rescue dives) and 36 of the 52 dive deaths were melee against monsters
    with eyes (giant bats, were-creatures, giant ants, rothes; Woodland-elves, ravens, cobras, soldier ants...), mostly
    fights of 3+ turns.

The camera (apply.c use_camera -> bhit(FLASHED_LIGHT) -> uhitm.c flash_hits_mon): the first monster on the line; one that
is awake, has eyes (M1_NOEYES), is not a light (S_LIGHT) and has no blinding attack of its own (yellow/black light,
Archon) is blinded: mcansee = 0 for good when adjacent (dist2 < 3 -> mblinded = 0), for rnd(1 + 50/dist2) turns at
distance 2; within dist2 < 9 it also flees 3 times in 4 (monflee rnd(100) turns, untimed 1 time in 4). A blind monster
can't see us: it keeps our square only while we stay on it (monmove.c set_apparxy), otherwise guesses within 1 square
(1 in 3 it finds us), skips 1 attack in 4 (monmove.c dochug), and swings at thin air when it guessed wrong (mhitu.c).
A sleeping target is woken by the flash -- only monsters seen to move or attack are flashed. Charges are plenty.

TOU_CAMERA: when the melee of the awake hostiles within 7 kills us within TOU_CAMERA_TURNS turns with P >= TOU_CAMERA_PDIE
(nhmodel.prayer.monster_turn_damage: to-hit against our AC, attacks, speed), flash the most damaging blindable hostile
within TOU_CAMERA_RANGE (2) that is first on its line (no pet, peaceful or remembered-invisible square in front).
TOU_CAMERA_WERE also flashes a were-creature in animal form within 2 while we are not yet a lycanthrope (grind killers:
werejackal 3, wererat 3; AD_WERE infects 1 bite in 4). A monster once blinded is not flashed again (resists_blnd) while
it is tracked; a flash that blinded nothing marks that square/name tried for TOU_CAMERA_RETRY turns.
TOU_QUAFF: HP < TOU_QUAFF_FRAC of max and P(death within 2 turns) >= TOU_QUAFF_PDIE -> a known (full / extra) healing
potion now (the emergency waits for HP < 1/3 or < 8); a due safe prayer still goes first (mino_guard._prayer_first).
"""
import math
import re

import nle.nethack as nh

from . import jf_config
from .combat.monster_utils import EXPLODING_MONSTERS, ONLY_RANGED_SLOW_MONSTERS, WEAK_MONSTERS
from .strategy import Strategy

M1_NOEYES = 0x00001000
S_LIGHT = 25                      # monsym.h (permonst.mlet holds the class index, not the map symbol)
S_HUMAN = 53
# AT_EXPL/AT_GAZE AD_BLND (mondata.c resists_blnd): lights explode blinding, the Archon gazes blinding
BLIND_ATTACKERS = frozenset(('yellow light', 'black light', 'Archon'))
WERE_FORMS = ('werejackal', 'wererat', 'werewolf')
DIRS = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))
_ATTACK_RE = r'The {} (?:hits|bites|butts|kicks|stings|swings|thrusts|touches|claws|misses|just misses)'
NO_FLASH = set(ONLY_RANGED_SLOW_MONSTERS) | set(EXPLODING_MONSTERS) | set(WEAK_MONSTERS)


def _mlet(mon):
    m = getattr(mon, 'mlet', '')
    return ord(m) if isinstance(m, str) and len(m) == 1 else m if isinstance(m, int) else -1


def blindable(mon):
    """flash_hits_mon would blind this kind (not M1_NOEYES, not S_LIGHT, no blinding attack of its own)."""
    name = getattr(mon, 'mname', 'unknown')
    if name == 'unknown' or name in BLIND_ATTACKERS:
        return False
    if int(getattr(mon, 'mflags1', 0) or 0) & M1_NOEYES:
        return False
    return _mlet(mon) != S_LIGHT


def is_were_animal(mon):
    return getattr(mon, 'mname', '') in WERE_FORMS and _mlet(mon) != S_HUMAN


def flash_blind_turns(dist2):
    """How long a flash at squared distance dist2 blinds (uhitm.c: dist2 < 3 -> for good; else rnd(1 + 50/dist2))."""
    if dist2 < 3:
        return 10 ** 6
    return 1 + 50 // dist2


def _cheb(a, b):
    return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1])))


def first_on_line(hero, target, occupied, max_range=2):
    """The direction (dy, dx) along which `target` is the first creature from `hero` (bhit stops at the first monster),
    or None: not on one of the 8 lines, farther than max_range, or another creature/'I' square in front of it.
    occupied: set of squares holding any creature (or a remembered invisible one), the target included."""
    dy, dx = int(target[0]) - int(hero[0]), int(target[1]) - int(hero[1])
    k = max(abs(dy), abs(dx))
    if k == 0 or k > max_range:
        return None
    if dy not in (0, k, -k) or dx not in (0, k, -k):
        return None
    d = (dy // k, dx // k)
    for i in range(1, k):
        if (hero[0] + d[0] * i, hero[1] + d[1] * i) in occupied:
            return None
    return d


def _phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def threat(hostiles, hp, ac, depth, xl, turns):
    """P(the melee of `hostiles` [(name, distance)] deals >= hp within `turns` turns), and each one's mean damage
    over them (same order). A monster d squares away joins after (d - 1) / speed turns. (as hea_kit.threat)"""
    from .nhmodel.prayer import monster_turn_damage
    mean = var = 0.0
    each = []
    for name, dist in hostiles:
        m1, v1, spd = monster_turn_damage(name, int(ac), int(depth), int(xl))
        t = max(0.0, turns - max(0, dist - 1) / max(spd, 0.25))
        each.append(m1 * spd * t)
        mean += m1 * spd * t
        var += v1 * spd * t
    if mean <= 0:
        return 0.0, each
    return 1.0 - _phi((hp - 0.5 - mean) / math.sqrt(max(var, 1.0))), each


def camera_charges(item):
    m = re.search(r'\((-?\d+):(-?\d+)\)', getattr(item, 'text', '') or '')
    return int(m.group(2)) if m else None


def is_tourist(agent):
    try:
        return agent.character.role == agent.character.TOURIST
    except Exception:  # noqa: BLE001
        return False


class TouKitGuard:
    def __init__(self, dive, mino):
        self.dive = dive
        self.agent = dive.agent
        self.mino = mino
        self.blind = {}       # (y, x) -> (mname, turn last matched, turn the blindness ends)
        self.tried = {}       # (y, x, mname) -> turn a flash there blinded nothing
        self.prev = {}        # (y, x) -> mname of the hostiles at the previous look
        self.prev_turn = None
        self.moved = {}       # (y, x) -> turn a hostile was seen arriving there (awake evidence)
        self.flashes = 0
        self.quaffs = 0
        self._tried_act = {}
        self._level = None

    # ------------------------------------------------------------------ state

    def _usable(self):
        agent = self.agent
        ch = agent.character
        # blind / hallucinating: names unknown; confused or stunned: getdir's confdir() may turn the flash
        if ch.prop.blind or ch.prop.polymorph or \
                any(getattr(ch.prop, p, False) for p in ('stoned', 'hallu', 'confusion', 'stun')):
            return False
        try:
            cond = int(agent.last_observation['blstats'][nh.NLE_BL_CONDITION])
        except Exception:  # noqa: BLE001
            cond = 0
        if cond & (nh.BL_MASK_STONE | nh.BL_MASK_SLIME | nh.BL_MASK_STRNGL | nh.BL_MASK_FOODPOIS | nh.BL_MASK_TERMILL):
            return False
        if agent.blstats.carrying_capacity >= 4:
            return False
        from .glyph import G
        from . import utils
        if utils.any_in(agent.glyphs, G.SWALLOW):
            return False
        return True

    def _camera(self):
        from . import opp_items
        st = opp_items.state(self.agent)
        for it in self.agent.inventory.items:
            if it.category == nh.TOOL_CLASS and it.is_unambiguous() and it.object == opp_items.CAMERA and \
                    it.text not in st.empty and 'unpaid' not in (it.text or ''):
                n = camera_charges(it)
                if n is None or n > jf_config.TOU_CAMERA_RESERVE:
                    return it
        return None

    def _observe(self):
        """Track hostiles' squares: arrivals (awake evidence) and the blinded ones as they move (greedy, by name)."""
        agent = self.agent
        now = int(agent.blstats.time)
        try:
            key = agent.current_level().key()
        except Exception:  # noqa: BLE001
            key = None
        if key != self._level:
            self._level = key
            self.blind.clear()
            self.tried.clear()
            self.prev = {}
            self.moved.clear()
        cur = {(int(m[1]), int(m[2])): getattr(m[3], 'mname', 'unknown') for m in agent.get_visible_monsters()}
        if self.prev_turn is not None and 0 < now - self.prev_turn <= 3:
            for pos, name in cur.items():
                if self.prev.get(pos) != name and \
                        any(n == name and _cheb(p, pos) <= 2 for p, n in self.prev.items()):
                    self.moved[pos] = now
        if self.prev_turn != now:
            self.prev, self.prev_turn = cur, now
        # follow the blinded monsters
        nb = {}
        for pos, (name, seen, until) in self.blind.items():
            if now >= until:
                continue
            if cur.get(pos) == name:
                nb[pos] = (name, now, until)
                continue
            near = [p for p, n in cur.items() if n == name and p not in nb and _cheb(p, pos) <= 1 + (now - seen)]
            if near:
                p = min(near, key=lambda q: _cheb(q, pos))
                nb[p] = (name, now, until)
                self.moved[p] = now
            elif now - seen <= 50:
                nb[pos] = (name, seen, until)   # out of view: kept a while (it may come back)
        self.blind = nb
        for k, t in list(self.tried.items()):
            if now - t > jf_config.TOU_CAMERA_RETRY:
                del self.tried[k]
        for p, t in list(self.moved.items()):
            if now - t > 20:
                del self.moved[p]
        return cur

    def _awake(self, m, msg, now):
        pos = (int(m[1]), int(m[2]))
        name = getattr(m[3], 'mname', 'unknown')
        if re.search(_ATTACK_RE.format(re.escape(name)), msg or ''):
            return True
        return now - self.moved.get(pos, -10 ** 9) <= 5

    def _hostiles(self):
        agent = self.agent
        pos = (int(agent.blstats.y), int(agent.blstats.x))
        out = []
        on_elb = (getattr(agent.inventory, 'engraving_below_me', '') or '').lower() == 'elbereth'
        for m in agent.get_visible_monsters():
            name = getattr(m[3], 'mname', 'unknown')
            if name in WEAK_MONSTERS:
                continue
            if on_elb and not self.dive._melee_ignores_elbereth(m[3]):
                continue
            d = _cheb((m[1], m[2]), pos)
            if d <= 7:
                out.append((m, d))
        return out

    def _occupied(self):
        agent = self.agent
        from .glyph import G
        from . import utils
        occ = set()
        mons = utils.isin(agent.glyphs, G.MONS) | utils.isin(agent.glyphs, G.PETS)
        for y, x in zip(*mons.nonzero()):
            occ.add((int(y), int(x)))
        inv = agent.glyphs == nh.GLYPH_INVISIBLE
        for y, x in zip(*inv.nonzero()):
            occ.add((int(y), int(x)))
        return occ

    # ------------------------------------------------------------------ plans

    def camera_plan(self):
        """('flash', camera, direction, target monster tuple, why) or None."""
        if not jf_config.TOU_CAMERA or not is_tourist(self.agent) or not self._usable():
            return None
        agent = self.agent
        cam = self._camera()
        if cam is None:
            return None
        self._observe()
        hostiles = self._hostiles()
        if not hostiles:
            return None
        bl = agent.blstats
        now = int(bl.time)
        msg = agent.message or ''
        awake = [(m, d) for m, d in hostiles if self._awake(m, msg, now)]
        if not awake:
            return None
        names = [(getattr(m[3], 'mname', 'unknown'), d) for m, d in awake]
        p_die, each = threat(names, bl.hitpoints, bl.armor_class, bl.depth, bl.experience_level,
                             jf_config.TOU_CAMERA_TURNS)
        hero = (int(bl.y), int(bl.x))
        occupied = self._occupied()
        cands = []
        for (m, d), dmg in zip(awake, each):
            pos = (int(m[1]), int(m[2]))
            name = getattr(m[3], 'mname', 'unknown')
            if name in NO_FLASH or not blindable(m[3]) or pos in self.blind or (pos[0], pos[1], name) in self.tried:
                continue
            direction = first_on_line(hero, pos, occupied, jf_config.TOU_CAMERA_RANGE)
            if direction is None:
                continue
            were = jf_config.TOU_CAMERA_WERE and d <= 2 and is_were_animal(m[3]) and \
                not agent.character.is_lycanthrope
            cands.append((d == 1, were, dmg, m, direction))
        if not cands:
            return None
        why = None
        if p_die >= jf_config.TOU_CAMERA_PDIE:
            why = f'P(death in {jf_config.TOU_CAMERA_TURNS} turns)={p_die:.2f}'
            # adjacent first (blinded for good), then the most damage
            cands.sort(key=lambda c: (c[0], c[2]), reverse=True)
        elif any(c[1] for c in cands):
            why = 'were in animal form'
            cands = [c for c in cands if c[1]]
            cands.sort(key=lambda c: (c[0], c[2]), reverse=True)
        if why is None:
            return None
        if self.mino._prayer_first():
            return None    # emergency_strategy (below) prays first
        adj, _, dmg, m, d = cands[0]
        direction = agent.calc_direction(bl.y, bl.x, bl.y + d[0], bl.x + d[1])
        return ('flash', cam, direction, m, f'{why}, target dmg {dmg:.1f}')

    def quaff_plan(self):
        """('quaff', potion, why) or None (TOU_QUAFF)."""
        if not jf_config.TOU_QUAFF or not is_tourist(self.agent) or not self._usable():
            return None
        agent = self.agent
        bl = agent.blstats
        if bl.hitpoints >= jf_config.TOU_QUAFF_FRAC * bl.max_hitpoints:
            return None
        hostiles = [(getattr(m[3], 'mname', 'unknown'), d) for m, d in self._hostiles() if d <= 3]
        if not hostiles:
            return None
        p_die, _ = threat(hostiles, bl.hitpoints, bl.armor_class, bl.depth, bl.experience_level, 2)
        if p_die < jf_config.TOU_QUAFF_PDIE:
            return None
        if self.mino._prayer_first():
            return None
        for name in ('full healing', 'extra healing', 'healing'):
            for it in agent.inventory.items:
                if it.category == nh.POTION_CLASS and it.is_unambiguous() and it.object.name == name and \
                        'unpaid' not in (it.text or ''):
                    return ('quaff', it, f'P(death in 2 turns)={p_die:.2f}, {name}')
        return None

    # ------------------------------------------------------------------ acting

    def _safe(self, planner):
        try:
            return planner()
        except Exception as e:  # noqa: BLE001
            agent = self.agent
            if getattr(self, '_err_turn', None) != agent.blstats.time:
                self._err_turn = agent.blstats.time
                agent.log(f'TOU_KIT {planner.__name__} error: {type(e).__name__}: {e}')
            return None

    def _blocked(self, key):
        now = self.agent.blstats.time
        t, n = self._tried_act.get(key, (None, 0))
        n = n + 1 if t == now else 1
        self._tried_act[key] = (now, n)
        return n > 2

    def _flash(self, plan):
        from . import opp_items
        _, cam, direction, m, why = plan
        agent = self.agent
        bl = agent.blstats
        pos = (int(m[1]), int(m[2]))
        name = getattr(m[3], 'mname', '?')
        dist2 = (pos[0] - int(bl.y)) ** 2 + (pos[1] - int(bl.x)) ** 2
        self.flashes += 1
        agent.log(f'TOU_CAMERA flashing {cam.text!r} {direction} at the {name} at {pos} ({why}), hp {bl.hitpoints}/'
                  f'{bl.max_hitpoints} (flash {self.flashes})')
        msg = opp_items.use_camera(agent, cam, direction) or ''
        now = int(agent.blstats.time)
        if 'blinded by the flash' in msg:
            self.blind[pos] = (name, now, now + flash_blind_turns(dist2))
        else:
            self.tried[(pos[0], pos[1], name)] = now
        agent.inventory.items.update(force=True)

    def strategy(self):
        def f():
            if not (jf_config.TOU_CAMERA or jf_config.TOU_QUAFF) or not is_tourist(self.agent):
                yield False
                return
            agent = self.agent
            plan = self._safe(self.camera_plan)
            if plan is not None and not self._blocked(('flash', plan[2])):
                yield True
                self._flash(plan)
                return
            plan = self._safe(self.quaff_plan)
            if plan is not None and not self._blocked(('quaff', plan[1].text)):
                yield True
                self.quaffs += 1
                agent.log(f'TOU_QUAFF {plan[1].text!r} ({plan[2]}), hp {agent.blstats.hitpoints}/'
                          f'{agent.blstats.max_hitpoints}')
                agent.inventory.quaff(plan[1])
                return
            yield False

        return Strategy(f)
