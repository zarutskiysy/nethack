"""Healer kit lane (jf_config.HEA_SLEEP_ZAP, HEA_SLEEP_WERE, HEA_QUAFF; off by default, role-gated in roles.py).

A Healer starts with a wand of sleep with 4-8 charges (u_init.c: WAN_SLEEP, UNDEF_SPE -> mkobj.c rn1(5,4)), 4 potions of
healing, 4 of extra healing, and the healing spells. It has no sleep resistance and the weakest melee of any role.
research/hea_kit.md measured 180 current-code dev games (au_heagno_/au_heahum_):
  * the wand is never zapped in the grind: fight2 never zaps sleep (item.is_offensive_usable_wand), and KNOWN_ITEMS acts
    only while diving, at critically low HP or after a burst -- and there it quaffs a potion before it zaps. 35 of the 39
    deep deaths with an inventory dump still held a charged wand (median 6 charges) and 5.4 healing potions on average;
  * 21 of 102 grind deaths (rothes, hill orcs, dwarves, giant ants, were-creatures) and 18 of 39 mid-dive deaths (soldier
    and fire ants, wolves, dwarf lords, centaurs) were melee fights against monsters a sleep ray stops: zap.c buzz ->
    zhitm ZT_SLEEP -> sleep_monst(d(6,25)): ~78 turns frozen (mcanmove = 0), resisted only by MR_SLEEP or the resist()
    roll rn2(100 + 12 - mlevel) < mr (rothe/hill orc/ants: mr 0);
  * the ray bounces (dobuzz: range rn1(7,7) = 7..13, -1 per square, -1 per bounce, -2 per creature it hits) and a
    Healer it hits falls asleep for d(6,25) turns (zhitu): KNOWN_ITEMS zapped at critical HP whatever was behind the
    target (RAY_CRIT_RUN = 0) and at monsters already asleep -- hea-gno s41 zapped one sleeping hill orc three times, the
    third ray came back and a second orc killed it asleep -- and at zombies, which resist (hea-hum s19: four charges);
  * an unused wand gets stolen (monkeys) or dropped (an Overloaded were form) and zapped back at us (hea-gno s29,
    hea-hum s80).

HEA_SLEEP_ZAP: when the melee of the awake hostiles around us (nhmodel.prayer.monster_turn_damage: to-hit against our
AC, attacks, speed; a monster d squares away joins after (d-1)/speed turns) kills us within HEA_SLEEP_TURNS turns with
P >= HEA_SLEEP_PDIE, zap the known wand of sleep along the line that takes most of that damage away -- only if our own
ray can't come back at us (P <= HEA_SLEEP_SELF_P over the ray's range, walls and bounces simulated as dobuzz does; an
unseen square counts as a wall) and no peaceful is on it. Monsters that resist sleep count for nothing. A monster the ray
hit is remembered as asleep while it stays on its square; then, with nothing awake threatening us, we melee it (it can't
fight back) unless a heal spell is due first. In the grind the last HEA_SLEEP_RESERVE charges wait for HEA_SLEEP_PDIE_LAST.
With the flag KNOWN_ITEMS leaves the wand of sleep to this guard (which sits above it).
HEA_SLEEP_WERE: also zap a were-creature in animal form within 2 squares while we are not yet a lycanthrope (mhitu.c
AD_WERE: 1 bite in 4 infects; 85 of the 180 games caught lycanthropy and each cure cost a prayer).
HEA_QUAFF: with no heal spell castable (Pw, hunger, failure rate), below HEA_QUAFF_FRAC of max HP and P(death within 2
turns) >= HEA_QUAFF_PDIE, quaff a known (full / extra) healing potion now instead of waiting for HP < 1/3 -- a due safe
prayer still goes first (mino_guard._prayer_first).
"""
import math
import re

import nle.nethack as nh

from . import castle_power, jf_config, power
from .combat.monster_utils import EXPLODING_MONSTERS, ONLY_RANGED_SLOW_MONSTERS, WEAK_MONSTERS
from .strategy import Strategy

DIRS = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))
RANGES = tuple(range(7, 14))      # dobuzz: rn1(7, 7)
P_MON_HIT = 0.95                  # zap_hit(mac) for AC 0..10: rn2(20) > 3 - ac, or rnd(10) < ac on a 0
P_SELF_HIT = 0.95                 # zap_hit(u.uac) for a Healer's AC
BCHANCE = 75                      # dobuzz make_bounce: 1/75 a diagonal ray reverses at an ordinary wall
SLEEP_MEMORY = 40                 # turns a monster the ray hit counts as asleep while it stays put (6d25: P(< 40) ~ 2%)
WERE_FORMS = ('werejackal', 'wererat', 'werewolf')
S_HUMAN = 53                      # monsym.h
NO_TOUCH = set(ONLY_RANGED_SLOW_MONSTERS) | set(EXPLODING_MONSTERS) | {'cockatrice', 'chickatrice'}
_ATTACK_RE = r'The {} (?:hits|bites|butts|kicks|stings|swings|thrusts|touches|claws|misses|just misses)'


# ---------------------------------------------------------------------------------------------- the ray (dobuzz)

def ray_outcomes(zap_pos, hero, d, mons, ranges=RANGES, p_mon=P_MON_HIT, p_self=P_SELF_HIT, bchance=BCHANCE):
    """Simulate our sleep ray from `hero` (y, x) in direction d = (dy, dx) as zap.c dobuzz does, averaged over the
    ranges. zap_pos[y][x]: the ray passes the square (else it bounces there); mons: {(y, x): kind} for every creature
    on the map (any kind). Returns (P(the ray hits us), {pos: P(it hits the creature there at least once)})."""
    h, w = len(zap_pos), len(zap_pos[0])
    hit_p = {}
    self_p = 0.0

    def ok(y, x):
        return (y, x) == hero or (0 <= y < h and 0 <= x < w and bool(zap_pos[y][x]))

    def run(y, x, dy, dx, rng, prob, hit):
        nonlocal self_p
        if prob < 1e-5:
            return
        while rng > 0:
            rng -= 1
            ly, lx = y, x
            y, x = y + dy, x + dx
            if (y, x) in mons and ok(y, x):
                if (y, x) not in hit:
                    # P_MON miss: the ray flies on with its range; hit: -2 and the creature is marked
                    run(y, x, dy, dx, rng, prob * (1 - p_mon), hit)
                    prob *= p_mon
                    hit = hit | {(y, x)}
                else:
                    # already hit once (asleep): it still costs range when the ray hits it again
                    run(y, x, dy, dx, rng, prob * (1 - p_mon), hit)
                    prob *= p_mon
                rng -= 2
            elif (y, x) == hero and rng >= 0:
                self_p += prob * p_self / len(ranges)
                prob *= 1 - p_self
                if prob <= 1e-6:
                    return
            if not ok(y, x):
                rng -= 1
                if dy == 0 or dx == 0:
                    dy, dx = -dy, -dx
                    continue
                side1 = ok(ly, x)       # (sx, lsy): keep x, flip dy
                side2 = ok(y, lx)       # (lsx, sy): keep y, flip dx
                rev = prob / bchance
                run(y, x, -dy, -dx, rng, rev, hit)
                rest = prob - rev
                if side1 and side2:
                    run(y, x, -dy, dx, rng, rest / 2, hit)
                    dx = -dx
                    prob = rest / 2
                elif side1:
                    dy = -dy
                    prob = rest
                elif side2:
                    dx = -dx
                    prob = rest
                else:
                    dy, dx = -dy, -dx
                    prob = rest
        for pos in hit:
            hit_p[pos] = hit_p.get(pos, 0.0) + prob / len(ranges)

    for r in ranges:
        run(hero[0], hero[1], d[0], d[1], r, 1.0, frozenset())
    return self_p, hit_p


# ---------------------------------------------------------------------------------------------- the threat

def _phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def threat(hostiles, hp, ac, depth, xl, turns):
    """P(the melee of `hostiles` [(name, distance)] deals >= hp within `turns` turns), and each one's mean damage
    over them (same order). A monster d squares away joins after (d - 1) / speed turns."""
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


# ---------------------------------------------------------------------------------------------- the guard

def _cheb(a, b):
    return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1])))


def charges(item):
    """Known charges of a wand from its text '(0:6)', else None."""
    m = re.search(r'\((-?\d+):(-?\d+)\)', getattr(item, 'text', '') or '')
    return int(m.group(2)) if m else None


def sleep_resisted(mon):
    """castle_power.zap_effect: the fraction of sleep a wand delivers to monster kind `mon` (0 = resists)."""
    try:
        return castle_power.zap_effect(mon, 'sleep')
    except Exception:  # noqa: BLE001
        return 1.0


def is_were_animal(mon):
    """A were-creature in its animal form (monsym.h: the @ form's class is S_HUMAN; only the animal bites AD_WERE)."""
    if getattr(mon, 'mname', '') not in WERE_FORMS:
        return False
    return castle_power._mlet(mon) != S_HUMAN


class HeaKitGuard:
    def __init__(self, dive, mino):
        self.dive = dive
        self.agent = dive.agent
        self.mino = mino
        self.slept = {}       # (y, x) -> (mname, turn the ray hit it)
        self.zaps = 0
        self.quaffs = 0
        self._tried = {}      # action key -> turn of the last attempt (no loop on a refused action)
        self._level = None    # the level the sleepers are on

    # ------------------------------------------------------------------ state

    def _usable(self):
        agent = self.agent
        ch = agent.character
        # blind / hallucinating: the monsters' names are unknown; confused or stunned: confdir() may turn the ray
        if ch.prop.blind or ch.prop.polymorph or \
                any(getattr(ch.prop, p, False) for p in ('stoned', 'hallu', 'confusion', 'stun')):
            return False
        try:
            cond = int(agent.last_observation['blstats'][nh.NLE_BL_CONDITION])
        except Exception:  # noqa: BLE001
            cond = 0
        if cond & (nh.BL_MASK_STONE | nh.BL_MASK_SLIME | nh.BL_MASK_STRNGL | nh.BL_MASK_FOODPOIS | nh.BL_MASK_TERMILL):
            return False   # emergency_strategy's business (lizard, prayer)
        if agent.blstats.carrying_capacity >= 4:   # dozap/dodrink: check_capacity refuses when Overtaxed
            return False
        from .glyph import G
        from . import utils
        if utils.any_in(agent.glyphs, G.SWALLOW):
            return False
        return True

    def _sleep_wand(self):
        for it in self.agent.inventory.items:
            if it.is_wand() and it.is_unambiguous() and it.object == castle_power._W['sleep'] and \
                    not power._empty(self.agent, it) and it.comment != 'EMPT':
                return it
        return None

    def _refresh_slept(self):
        """Forget sleepers that moved, died or hit us since (a resisted ray leaves them awake)."""
        agent = self.agent
        now = agent.blstats.time
        msg = agent.message or ''
        try:
            key = agent.current_level().key()
        except Exception:  # noqa: BLE001
            key = None
        if key != self._level:
            self._level = key
            self.slept.clear()
        if not self.slept:
            return
        seen = {(int(m[1]), int(m[2])): getattr(m[3], 'mname', '') for m in agent.get_visible_monsters()}
        for pos, (name, t) in list(self.slept.items()):
            if now - t > SLEEP_MEMORY or seen.get(pos) != name or \
                    re.search(_ATTACK_RE.format(re.escape(name)), msg):
                del self.slept[pos]

    def _hostiles(self):
        """Awake, non-trivial hostiles in view: [(monster tuple, distance)]."""
        agent = self.agent
        pos = (int(agent.blstats.y), int(agent.blstats.x))
        out = []
        on_elb = (agent.inventory.engraving_below_me or '').lower() == 'elbereth'
        for m in agent.get_visible_monsters():
            name = getattr(m[3], 'mname', 'unknown')
            if name in WEAK_MONSTERS or (int(m[1]), int(m[2])) in self.slept:
                continue
            if on_elb and not self.dive._melee_ignores_elbereth(m[3]):
                continue
            d = _cheb((m[1], m[2]), pos)
            if d <= 7:
                out.append((m, d))
        return out

    def _zap_pos(self):
        return self.agent.current_level().walkable

    def _creatures(self):
        """Every creature on the map as {(y, x): kind}: 'hostile' (with its tuple), 'pet', 'peaceful'."""
        agent = self.agent
        from .glyph import G
        from . import utils
        out = {}
        for m in agent.get_visible_monsters():
            out[(int(m[1]), int(m[2]))] = ('hostile', m)
        pets = utils.isin(agent.glyphs, G.PETS)
        for y, x in zip(*pets.nonzero()):
            out[(int(y), int(x))] = ('pet', None)
        mons = utils.isin(agent.glyphs, G.MONS)
        me = (int(agent.blstats.y), int(agent.blstats.x))
        for y, x in zip(*mons.nonzero()):
            if (int(y), int(x)) not in out and (int(y), int(x)) != me:
                out[(int(y), int(x))] = ('peaceful', None)
        return out

    # ------------------------------------------------------------------ plans

    def _best_line(self, hostiles, weights):
        """The zap direction that puts to sleep the most expected damage: (gain, direction, hits [(m, p)], self_p)."""
        agent = self.agent
        hero = (int(agent.blstats.y), int(agent.blstats.x))
        creatures = self._creatures()
        zap_pos = self._zap_pos()
        weight = {(int(m[1]), int(m[2])): w for (m, _), w in zip(hostiles, weights)}
        best = None
        for d in DIRS:
            # a direction is worth simulating only with a hostile we care about on its line within reach
            if not any(self._on_line(hero, pos, d) for pos in weight):
                continue
            self_p, hit_p = ray_outcomes(zap_pos, hero, d, {p: k for p, k in creatures.items()})
            if self_p > jf_config.HEA_SLEEP_SELF_P:
                continue
            if any(creatures[p][0] == 'peaceful' and q > 0.01 for p, q in hit_p.items()):
                continue
            gain = 0.0
            hits = []
            for p, q in hit_p.items():
                kind, m = creatures[p]
                if kind != 'hostile' or p in self.slept:
                    continue
                eff = sleep_resisted(m[3])
                gain += q * eff * weight.get(p, 0.0)
                if eff > 0:
                    hits.append((m, q))
            if gain > 0 and (best is None or gain > best[0]):
                best = (gain, d, hits, self_p)
        return best

    @staticmethod
    def _on_line(hero, pos, d):
        dy, dx = pos[0] - hero[0], pos[1] - hero[1]
        k = max(abs(dy), abs(dx))
        if k == 0 or k > jf_config.HEA_SLEEP_RANGE:
            return False
        return (dy, dx) == (d[0] * k, d[1] * k)

    def _threshold(self, wand):
        n = charges(wand)
        if not self.dive.diving and n is not None and n <= jf_config.HEA_SLEEP_RESERVE:
            return jf_config.HEA_SLEEP_PDIE_LAST
        return jf_config.HEA_SLEEP_PDIE

    def zap_plan(self):
        """('zap', wand, direction, why, hits) or None. Side-effect free apart from forgetting stale sleepers."""
        if not (jf_config.HEA_SLEEP_ZAP or jf_config.HEA_SLEEP_WERE) or not self._usable():
            return None
        agent = self.agent
        from .combat import fight_heur
        if fight_heur.missiles_risk_the_watch(agent):
            return None
        wand = self._sleep_wand()
        if wand is None:
            return None
        self._refresh_slept()
        hostiles = self._hostiles()
        if not hostiles:
            return None
        bl = agent.blstats
        names = [(getattr(m[3], 'mname', 'unknown'), d) for m, d in hostiles]
        p_die, each = threat(names, bl.hitpoints, bl.armor_class, bl.depth, bl.experience_level,
                             jf_config.HEA_SLEEP_TURNS)
        why = None
        weights = each
        if jf_config.HEA_SLEEP_ZAP and p_die >= self._threshold(wand):
            why = f'P(death in {jf_config.HEA_SLEEP_TURNS} turns)={p_die:.2f}'
        elif jf_config.HEA_SLEEP_WERE and not agent.character.is_lycanthrope:
            weres = [i for i, (m, d) in enumerate(hostiles) if d <= 2 and is_were_animal(m[3])]
            if weres:
                why = f'were in animal form at {hostiles[weres[0]][1]}'
                weights = [1.0 if i in weres else 0.0 for i in range(len(hostiles))]
        if why is None:
            return None
        if self.mino._prayer_first():
            return None    # emergency_strategy (below) prays first: 3 invulnerable turns and full HP
        best = self._best_line(hostiles, weights)
        if best is None:
            return None
        gain, d, hits, self_p = best
        if gain < jf_config.HEA_SLEEP_MIN_SHARE * sum(weights):
            return None
        direction = agent.calc_direction(bl.y, bl.x, bl.y + d[0], bl.x + d[1])
        return ('zap', wand, direction, f'{why}, gain {gain:.1f}/{sum(weights):.1f}, self {self_p:.3f}', hits)

    def kill_plan(self):
        """('melee', (y, x), name) at a sleeper next to us when nothing awake threatens us, else None."""
        if not (jf_config.HEA_SLEEP_ZAP or jf_config.HEA_SLEEP_WERE) or not self.slept or not self._usable():
            return None
        agent = self.agent
        self._refresh_slept()
        bl = agent.blstats
        pos = (int(bl.y), int(bl.x))
        adj = [(p, n) for p, (n, _) in self.slept.items() if _cheb(p, pos) == 1 and n not in NO_TOUCH]
        if not adj:
            return None
        awake = [(getattr(m[3], 'mname', 'unknown'), d) for m, d in self._hostiles() if d <= 3]
        if awake:
            p_die, _ = threat(awake, bl.hitpoints, bl.armor_class, bl.depth, bl.experience_level, 3)
            if p_die >= 0.05:
                return None
        if agent.should_cast_extra_heal() or agent.should_cast_heal() or self.mino._prayer_first():
            return None    # heal / pray first (emergency_strategy, below us): the sleeper waits
        return ('melee', adj[0][0], adj[0][1])

    def quaff_plan(self):
        """('quaff', potion, why) or None (HEA_QUAFF)."""
        if not jf_config.HEA_QUAFF or not self._usable():
            return None
        agent = self.agent
        bl = agent.blstats
        if bl.hitpoints >= jf_config.HEA_QUAFF_FRAC * bl.max_hitpoints:
            return None
        if agent.should_cast_extra_heal() or agent.should_cast_heal():
            return None
        if agent.character.prop.polymorph:
            return None
        hostiles = [(getattr(m[3], 'mname', 'unknown'), d) for m, d in self._hostiles() if d <= 3]
        if not hostiles:
            return None
        p_die, _ = threat(hostiles, bl.hitpoints, bl.armor_class, bl.depth, bl.experience_level, 2)
        if p_die < jf_config.HEA_QUAFF_PDIE:
            return None
        if self.mino._prayer_first():
            return None
        for name in ('full healing', 'extra healing', 'healing'):
            for it in agent.inventory.items:
                if it.category == nh.POTION_CLASS and it.is_unambiguous() and it.object.name == name:
                    return ('quaff', it, f'P(death in 2 turns)={p_die:.2f}, {name}')
        return None

    # ------------------------------------------------------------------ acting

    def _safe(self, planner):
        """A planner's result; an unexpected error in the (pure) planning is logged once per turn and means no plan."""
        try:
            return planner()
        except Exception as e:  # noqa: BLE001
            agent = self.agent
            if getattr(self, '_err_turn', None) != agent.blstats.time:
                self._err_turn = agent.blstats.time
                agent.log(f'HEA_KIT {planner.__name__} error: {type(e).__name__}: {e}')
            return None

    def _blocked(self, key):
        """The same action twice in one game turn: it was refused (no time passed) -- skip it for this turn."""
        now = self.agent.blstats.time
        t, n = self._tried.get(key, (None, 0))
        n = n + 1 if t == now else 1
        self._tried[key] = (now, n)
        return n > 2

    def _zap(self, plan):
        _, wand, direction, why, hits = plan
        agent = self.agent
        bl = agent.blstats
        self.zaps += 1
        names = [getattr(m[3], 'mname', '?') for m, _ in hits]
        agent.log(f'HEA_SLEEP zapping {wand.text!r} {direction} ({why}) at {names}, hp {bl.hitpoints}/'
                  f'{bl.max_hitpoints} (zap {self.zaps})')
        agent.zap(wand, direction)
        msg = agent.message or ''
        agent.log(f'HEA_SLEEP zap -> {msg[:160]!r}')
        if 'Nothing happens' in msg or 'You wrest' in msg:
            agent.inventory.empty_wands.add(wand.text)
        now = agent.blstats.time
        for m, _ in hits:
            name = getattr(m[3], 'mname', '?')
            if f'hits the {name}' in msg or f'sleep ray hits the {name}' in msg:
                self.slept[(int(m[1]), int(m[2]))] = (name, now)
        agent.inventory.items.update(force=True)

    def strategy(self):
        def f():
            if not (jf_config.HEA_SLEEP_ZAP or jf_config.HEA_SLEEP_WERE or jf_config.HEA_QUAFF):
                yield False
                return
            agent = self.agent
            plan = self._safe(self.zap_plan)
            if plan is not None and not self._blocked(('zap', plan[2])):
                yield True
                self._zap(plan)
                return
            plan = self._safe(self.quaff_plan)
            if plan is not None and not self._blocked(('quaff', plan[1].text)):
                yield True
                self.quaffs += 1
                agent.log(f'HEA_QUAFF {plan[1].text!r} ({plan[2]}), hp {agent.blstats.hitpoints}/'
                          f'{agent.blstats.max_hitpoints}')
                agent.inventory.quaff(plan[1])
                return
            plan = self._safe(self.kill_plan)
            if plan is not None and not self._blocked(('melee', plan[1])):
                yield True
                (y, x), name = plan[1], plan[2]
                if not agent._keep_digging_tool_wielded() and agent.wield_best_melee_weapon():
                    return
                agent.log(f'HEA_SLEEP hitting the sleeping {name} at ({y},{x})')
                agent.melee_attack(y, x)
                return
            yield False

        return Strategy(f)
