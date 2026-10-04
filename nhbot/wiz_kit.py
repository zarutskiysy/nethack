"""Wizard kit lane (jf_config.WIZ_WAND_FIGHT, WIZ_SPEED_SELF, WIZ_KIT_BOOST, WIZ_RING_SAFE; off by default, gated to
the roles in WIZ_KIT_ROLES and switched on per identity in roles.py).

u_init.c Wizard[]: a quarterstaff, a cloak of magic resistance, ONE random wand (mkobj: any wand but wishing and nothing,
so 31% an attack wand -- striking 7.7%, sleep/magic missile 5.2%, fire/cold/lightning 4.1%, death 0.5% -- plus
teleportation 4.6%, speed monster 5.2%, digging 5.7%), two different random rings (never levitation, hunger, aggravate
monster; a chargeable one is positive), three potions, three scrolls (never amnesia, fire, blank) and force bolt plus one
random level 1-3 spellbook (sleep 7%), all uncursed with their BUC and type known. research/wiz_kit.md measured the 500
current-code dev games of g0w (5 Wizard identities x 100 seeds):
  * the starting wand is never used in the grind: fight2 zaps only rays (never sleep, never striking: a beam) and not
    at all while force bolt is castable (FB_OVER_RAYS); KNOWN_ITEMS acts only in the dive at critical HP. 46 of the
    180 Dlvl-20+ inventory dumps still held the starting attack wand with 4.6 charges on average (40 with >= 3);
    the 225 grind deaths (45% of games) are mostly melee at XL 5-7 (rothes, giant ants, hill orcs, dwarves) with the
    Pw spent;
  * the 9 Dlvl-20+ dumps with a wand of speed monster had never zapped it (intrinsic speed: zap.c zapyourself);
  * of the always-wear rings (free action, poison resistance, gain Str/Con) held at Dlvl 20+, 16 of 64 were worn: the
    dig-dive never runs gather_items, and the hunger shedding's put-back matched the ring by its inventory text, which
    still said '(on left hand)'. Rings of regeneration (17) and stealth (17) were never worn;
  * gain level 11, gain energy 22, gain ability 21 potions and 11 scrolls of enchant armor were still carried unused.

WIZ_WAND_FIGHT: when the awake hostiles' melee kills us within WIZ_WAND_TURNS turns with P >= WIZ_WAND_PDIE, use the
known attack item that removes the most of that damage: a wand of sleep / death / teleportation (decisive), fire / cold /
lightning / magic missile / striking (damage: P(kill) from the monster's level and the dice), or the sleep SPELL (5 Pw).
Rays are simulated as dobuzz does (hea_kit.ray_outcomes: range 7..13, bounces, -2 per creature hit) and refused when our
own ray can come back at us (P > WIZ_WAND_SELF_P) unless it can't hurt us (magic missile / death with the cloak of magic
resistance worn, sleep for an elf from XL 4); beams (striking, teleportation) fly 6..13 squares, -3 per creature, and stop
at walls (zap.c bhit). No line with a pet or peaceful on it, no beam from Elbereth (bhitm wakes via_attack: hypocrisy), no
zap in Minetown, with the watch or a shopkeeper in view. A damage wand waits for WIZ_WAND_PDIE_BOLT while force bolt is
castable (fight2's bolt does the same 2d12 for 5 Pw). In the grind the last WIZ_WAND_RESERVE charges wait for
WIZ_WAND_PDIE_LAST. Monsters our sleep hit are remembered and meleed when nothing awake threatens us (hea_kit).
WIZ_SPEED_SELF: zap a known wand of speed monster at ourselves once, out of a fight (intrinsic Fast for good).
WIZ_KIT_BOOST: out of a fight, quaff known non-cursed potions of gain level / gain energy / gain ability and read a known
non-cursed scroll of enchant armor while every worn piece is +3 or less (read.c: above +3 a piece may evaporate).
WIZ_RING_SAFE: out of a fight and above the ring module's MAX_DEPTH, put back on an always-wear ring (the module's list
plus WIZ_RING_EXTRA) that is off (not while Weak); wear a known ring of regeneration while HP < WIZ_REGEN_ON of max and
take it off at WIZ_REGEN_OFF or when Weak (eat.c: +1 nutrition every other turn; resting heals 1 HP a turn instead of
~1 per 6 at XL 6, so a long rest costs less food with it than without).
"""
import math
import re

import nle.nethack as nh

from . import castle_power, hea_kit, jf_config, power, utils
from .combat.monster_utils import WEAK_MONSTERS
from .glyph import G, Hunger
from .hea_kit import DIRS, NO_TOUCH, _cheb, charges, ray_outcomes, threat

RAYS = ('sleep', 'death', 'fire', 'cold', 'lightning', 'magic missile')
BEAMS = ('teleportation', 'striking')
DECISIVE = ('sleep', 'death', 'teleportation')
FIGHT_WANDS = DECISIVE + ('fire', 'cold', 'lightning', 'magic missile', 'striking')
DICE = {'fire': (6, 6), 'cold': (6, 6), 'lightning': (6, 6), 'magic missile': (2, 6), 'striking': (2, 12)}
BEAM_RANGES = tuple(range(6, 14))     # zap.c weffects -> bhit(..., rn1(8, 6), ...)
DAMAGE_PARTIAL = 0.25                 # a damage zap that doesn't kill still shortens the fight
SPELL_SLEEP = 'sleep'
_PREF = {'spell': 0, 'decisive': 1, 'damage': 2}


def _phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def p_kill(mon, kind):
    """P(one hit of `kind` -- fire/cold/lightning/magic missile/striking -- kills monster kind `mon`): its HP is
    mlevel d8 (makemon.c; 1d4 at level 0), the damage nd d sides (zap.c zhitm: 6d6 for a wand's fire/cold/lightning,
    2d6 magic missile; bhitm: striking 2d12, hitting when rnd(20) < 10 + its AC)."""
    lvl = max(0, int(getattr(mon, 'mlevel', 0) or 0))
    hp_m, hp_v = (2.5, 1.25) if lvl == 0 else (4.5 * lvl, 5.25 * lvl)
    n, s = DICE[kind]
    d_m, d_v = n * (s + 1) / 2.0, n * (s * s - 1) / 12.0
    p = 1.0 - _phi((hp_m - d_m - 0.5) / math.sqrt(hp_v + d_v))
    if kind == 'striking':
        ac = int(getattr(mon, 'ac', 5) if getattr(mon, 'ac', None) is not None else 5)
        p *= min(1.0, max(0.0, (9 + ac) / 20.0))
    return p


def effect(mon, kind):
    """The fraction of monster `mon`'s threat one hit of `kind` removes (0 when it resists)."""
    base = castle_power.zap_effect(mon, kind) if kind in castle_power._ZAP_GOOD else 1.0
    if base <= 0:
        return 0.0
    if kind in DECISIVE:
        return base
    pk = p_kill(mon, kind)
    return base * (pk + DAMAGE_PARTIAL * (1 - pk))


def beam_outcomes(zap_pos, hero, d, mons, ranges=BEAM_RANGES):
    """zap.c bhit for an IMMEDIATE wand: from `hero` in direction d, range 6..13, -1 a square, -3 for every creature
    it reaches, stopping at the first square it can't pass. {pos: P(the beam reaches the creature there)}."""
    h, w = len(zap_pos), len(zap_pos[0])
    out = {}
    for r in ranges:
        y, x = hero
        rng = r
        while rng > 0:
            rng -= 1
            y, x = y + d[0], x + d[1]
            if not (0 <= y < h and 0 <= x < w) or not zap_pos[y][x]:
                break
            if (y, x) in mons:
                out[(y, x)] = out.get((y, x), 0.0) + 1.0 / len(ranges)
                rng -= 3
    return out


def _wand_name(item):
    obj = getattr(item, 'object', None)
    for name in FIGHT_WANDS + ('speed monster',):
        if obj is not None and obj == castle_power._W.get(name):
            return name
    return None


def _buc_known_ok(item):
    """The game printed the item as uncursed or blessed (a starting item always shows its BUC)."""
    t = getattr(item, 'text', '') or ''
    return bool(re.search(r'\b(uncursed|blessed)\b', t)) and 'unpaid' not in t


class WizKitGuard(hea_kit.HeaKitGuard):
    def __init__(self, dive, mino):
        super().__init__(dive, mino)
        self.speed_done = False
        self.boosts = {}          # item text -> tries
        self.ring_tries = {}      # ring glyph -> turn of the last put on / remove we started
        self.regen_glyph = None   # the ring of regeneration we put on (the only one we take off)

    # ------------------------------------------------------------------ gates

    def _role_ok(self):
        roles = jf_config.WIZ_KIT_ROLES
        if roles is None:
            return True
        from .item.ring_amulet_logic import _role_in
        try:
            return _role_in(self.agent, roles)
        except Exception:  # noqa: BLE001
            return False

    def _is_monk(self):
        from .character import Character
        return getattr(self.agent.character, 'role', None) == Character.MONK

    def _fight_lane(self):
        """The fight lane (fight_plan) acts for us: WIZ_WAND_FIGHT for the WIZ_KIT_ROLES, or MON_SLEEP_FIGHT for a Monk
        (its starting sleep spell, a third of Monks, and the attack wands it finds)."""
        if jf_config.WIZ_WAND_FIGHT and self._role_ok():
            return True
        return bool(jf_config.MON_SLEEP_FIGHT) and self._is_monk()

    def _calm(self, radius=6):
        """No hostile within `radius` (Chebyshev) and nothing hurt us this turn."""
        agent = self.agent
        pos = (int(agent.blstats.y), int(agent.blstats.x))
        return not any(_cheb((m[1], m[2]), pos) <= radius for m in agent.get_visible_monsters())

    def _in_shop_view(self):
        agent = self.agent
        try:
            if utils.any_in(agent.glyphs, G.SHOPKEEPER):
                return True
        except Exception:  # noqa: BLE001
            pass
        return any('unpaid' in (getattr(i, 'text', '') or '') for i in agent.inventory.items)

    # ------------------------------------------------------------------ what we have

    def _fight_items(self):
        """[(kind, name, item or None)] -- kind 'spell' / 'decisive' / 'damage'; item None for the sleep spell."""
        agent = self.agent
        out = []
        ch = agent.character
        spells = getattr(ch, 'known_spells', {}) or {}
        if jf_config.WIZ_SLEEP_SPELL and SPELL_SLEEP in spells and agent.blstats.energy >= 5 and \
                getattr(ch, 'spell_fail_chance', {}).get(SPELL_SLEEP, 1) <= 0.3 and \
                agent.blstats.hunger_state < Hunger.WEAK and agent.blstats.carrying_capacity < 2:
            from .combat import fight_heur
            if not fight_heur._fb_cannot_cast(agent):
                out.append(('spell', SPELL_SLEEP, None))
        for it in agent.inventory.items:
            if not (it.is_wand() and it.is_unambiguous()) or power._empty(agent, it) or it.comment == 'EMPT':
                continue
            name = _wand_name(it)
            if name in FIGHT_WANDS:
                out.append(('decisive' if name in DECISIVE else 'damage', name, it))
        return out

    def _mr_worn(self):
        return any(getattr(i, 'equipped', False) and 'magic resistance' in (getattr(i, 'text', '') or '')
                   for i in self.agent.inventory.items)

    def _sleep_resistant(self):
        from .character import Character
        ch = self.agent.character
        if getattr(ch, 'race', None) == Character.ELF and self.agent.blstats.experience_level >= 4:
            return True   # attrib.c elf_abil: sleep resistance at XL 4
        if jf_config.MON_SLEEP_FIGHT and getattr(ch, 'role', None) == Character.MONK:
            return True   # attrib.c mon_abil: sleep resistance at XL 1
        return False

    def _self_harmless(self, name):
        if name in ('magic missile', 'death'):
            return self._mr_worn()   # zap.c zhitu: Antimagic -> 'the missiles bounce off' / 'You aren't affected'
        if name == 'sleep':
            return self._sleep_resistant()
        return False

    # ------------------------------------------------------------------ the fight plan

    def _line_gain(self, name, kind, d, hero, creatures, zap_pos, weight):
        """(gain, hits [(m, p)], self_p) of `name` along direction d, or None when the line is refused."""
        if name in RAYS:
            harmless = self._self_harmless(name)
            # a ray that can't hurt us flies on through our square (buzz: zap_hit(u.uac) then zhitu; the hea_kit model
            # stops crediting hits after the ray reaches us, so it runs with p_self = 0 here)
            self_p, hit_p = ray_outcomes(zap_pos, hero, d, {p: k for p, k in creatures.items()},
                                         p_self=0.0 if harmless else hea_kit.P_SELF_HIT)
            if self_p > jf_config.WIZ_WAND_SELF_P and not harmless:
                return None
        else:
            self_p, hit_p = 0.0, beam_outcomes(zap_pos, hero, d, creatures)
        if any(creatures[p][0] in ('peaceful', 'pet') and q > 0.01 for p, q in hit_p.items()):
            return None
        gain = 0.0
        hits = []
        for p, q in hit_p.items():
            k, m = creatures[p]
            if k != 'hostile' or p in self.slept:
                continue
            eff = effect(m[3], name)
            gain += q * eff * weight.get(p, 0.0)
            if eff > 0:
                hits.append((m, q))
        return gain, hits, self_p

    def fight_plan(self):
        """('zap' | 'cast', item or None, name, (dy, dx), why, hits) or None. Side-effect free apart from forgetting
        stale sleepers."""
        if not self._fight_lane() or not self._usable():
            return None
        agent = self.agent
        from .combat import fight_heur
        if fight_heur.missiles_risk_the_watch(agent) or utils.any_in(agent.glyphs, G.SHOPKEEPER):
            return None
        items = self._fight_items()
        if not items:
            return None
        self._refresh_slept()
        hostiles = self._hostiles()
        if not hostiles:
            return None
        bl = agent.blstats
        names = [(getattr(m[3], 'mname', 'unknown'), d) for m, d in hostiles]
        p_die, each = threat(names, bl.hitpoints, bl.armor_class, bl.depth, bl.experience_level,
                             jf_config.WIZ_WAND_TURNS)
        if p_die < jf_config.WIZ_WAND_PDIE:
            return None
        if self.mino._prayer_first():
            return None    # emergency_strategy (below) prays first: 3 invulnerable turns and full HP
        bolt = fight_heur._fb_castable(agent)
        on_elb = (agent.inventory.engraving_below_me or '').lower() == 'elbereth'
        hero = (int(bl.y), int(bl.x))
        creatures = self._creatures()
        zap_pos = self._zap_pos()
        weight = {(int(m[1]), int(m[2])): w for (m, _), w in zip(hostiles, each)}
        total = sum(each)
        best = None
        for kind, name, it in items:
            if kind == 'damage' and bolt and p_die < jf_config.WIZ_WAND_PDIE_BOLT:
                continue
            if it is not None and not self.dive.diving:
                n = charges(it)
                if n is not None and n <= jf_config.WIZ_WAND_RESERVE and p_die < jf_config.WIZ_WAND_PDIE_LAST:
                    continue
            if on_elb and name in BEAMS:
                continue
            for d in DIRS:
                if not any(self._on_line_r(hero, pos, d, jf_config.WIZ_WAND_RANGE) for pos in weight):
                    continue
                r = self._line_gain(name, kind, d, hero, creatures, zap_pos, weight)
                if r is None:
                    continue
                gain, hits, self_p = r
                if gain <= 0 or gain < jf_config.WIZ_WAND_MIN_SHARE * total:
                    continue
                key = (gain, -_PREF[kind])
                if best is None or key[0] > best[0][0] * 1.1 or \
                        (key[0] >= best[0][0] * 0.9 and key[1] > best[0][1]):
                    best = (key, kind, name, it, d, hits, self_p)
        if best is None:
            return None
        (gain, _), kind, name, it, d, hits, self_p = best
        why = f'P(death in {jf_config.WIZ_WAND_TURNS} turns)={p_die:.2f}, gain {gain:.1f}/{total:.1f}, self {self_p:.3f}'
        return ('cast' if kind == 'spell' else 'zap', it, name, d, why, hits)

    @staticmethod
    def _on_line_r(hero, pos, d, reach):
        dy, dx = pos[0] - hero[0], pos[1] - hero[1]
        k = max(abs(dy), abs(dx))
        if k == 0 or k > reach:
            return False
        return (dy, dx) == (d[0] * k, d[1] * k)

    def kill_plan(self):
        """('melee', (y, x), name) at a sleeper next to us when nothing awake threatens us, else None."""
        if not (jf_config.WIZ_WAND_FIGHT or jf_config.MON_SLEEP_FIGHT) or not self.slept or not self._usable():
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
        if self.mino._prayer_first():
            return None
        return ('melee', adj[0][0], adj[0][1])

    # ------------------------------------------------------------------ out of a fight

    def speed_plan(self):
        if not jf_config.WIZ_SPEED_SELF or self.speed_done or not self._role_ok() or not self._usable():
            return None
        if not self._calm():
            return None
        for it in self.agent.inventory.items:
            if it.is_wand() and it.is_unambiguous() and _wand_name(it) == 'speed monster' and \
                    not power._empty(self.agent, it) and it.comment != 'EMPT':
                return ('zapself', it)
        return None

    def boost_plan(self):
        if not jf_config.WIZ_KIT_BOOST or not self._role_ok() or not self._usable():
            return None
        agent = self.agent
        ch = agent.character
        if getattr(ch.prop, 'confusion', False) or getattr(ch.prop, 'stun', False) or getattr(ch.prop, 'hallu', False):
            return None
        if not self._calm() or self._in_shop_view():
            return None
        for it in agent.inventory.items:
            if not it.is_unambiguous() or not _buc_known_ok(it) or self.boosts.get(it.text, 0) >= 2:
                continue
            name = getattr(it.object, 'name', '')
            if it.category == nh.POTION_CLASS and name in jf_config.WIZ_BOOST_POTIONS:
                return ('quaff', it, name)
            if it.category == nh.SCROLL_CLASS and name == 'enchant armor':
                worn = [i for i in agent.inventory.items if i.is_armor() and i.equipped]
                if worn and all((i.modifier or 0) <= 3 for i in worn):
                    return ('read', it, name)
        return None

    def _ring_slots(self):
        return sum(1 for i in self.agent.inventory.items if i.category == nh.RING_CLASS and i.equipped)

    def ring_plan(self):
        """('puton' | 'remove', ring, why) or None."""
        if not jf_config.WIZ_RING_SAFE or not self._role_ok() or not self._usable():
            return None
        agent = self.agent
        from .item import ring_amulet_config as rcfg
        from .item.ring_amulet_logic import _safe_to_put_on, _puton_blocked
        bl = agent.blstats
        if bl.depth >= rcfg.MAX_DEPTH:
            return None
        try:
            if int(agent.last_observation['blstats'][nh.NLE_BL_CONDITION]) & nh.BL_MASK_LEV:
                return None
        except Exception:  # noqa: BLE001
            pass
        inv = agent.inventory
        now = bl.time
        weak = bl.hunger_state >= Hunger.WEAK
        rings = [i for i in inv.items if i.category == nh.RING_CLASS and i.is_unambiguous()]

        def recent(it):
            return now - self.ring_tries.get(it.glyphs[0], -10 ** 9) < jf_config.WIZ_RING_RETRY

        # regeneration: off when healed or Weak (needs no calm: #remove is one action)
        regen = [i for i in rings if i.object.name == 'regeneration']
        worn_regen = next((i for i in regen if i.equipped and i.glyphs[0] == self.regen_glyph), None)
        if worn_regen is not None and (weak or bl.hitpoints >= jf_config.WIZ_REGEN_OFF * bl.max_hitpoints) and \
                not recent(worn_regen) and self._calm(1):
            return ('remove', worn_regen, 'regeneration: healed' if not weak else 'regeneration: Weak')
        if weak:
            return None
        free = self._ring_slots() < 2
        if not free:
            return None
        if bl.hitpoints < jf_config.WIZ_REGEN_ON * bl.max_hitpoints and self._calm(1):
            it = next((i for i in regen if not i.equipped and _safe_to_put_on(inv, i) and not recent(i) and
                       not _puton_blocked(inv, i)), None)
            if it is not None:
                return ('puton', it, f'regeneration: hp {bl.hitpoints}/{bl.max_hitpoints}')
        if not self._calm():
            return None
        wanted = tuple(rcfg.ALWAYS_WEAR_RINGS) + tuple(jf_config.WIZ_RING_EXTRA or ())
        for name in wanted:
            it = next((i for i in rings if i.object.name == name and not i.equipped and _safe_to_put_on(inv, i)
                       and not recent(i) and not _puton_blocked(inv, i)
                       and i.glyphs[0] not in getattr(inv, '_known_stuck_ring_amulet_glyphs', set())), None)
            if it is not None:
                return ('puton', it, f'always-wear {name}')
        return None

    # ------------------------------------------------------------------ acting

    def _act_fight(self, plan):
        verb, it, name, d, why, hits = plan
        agent = self.agent
        bl = agent.blstats
        self.zaps += 1
        names = [getattr(m[3], 'mname', '?') for m, _ in hits]
        what = f'the {name} spell' if it is None else repr(it.text)
        agent.log(f'WIZ_KIT {verb} {what} {d} ({why}) at {names}, hp {bl.hitpoints}/{bl.max_hitpoints} '
                  f'pw {bl.energy} (use {self.zaps})')
        if verb == 'cast':
            agent.cast(SPELL_SLEEP, d)
        else:
            direction = agent.calc_direction(bl.y, bl.x, bl.y + d[0], bl.x + d[1])
            agent.zap(it, direction)
        msg = agent.message or ''
        agent.log(f'WIZ_KIT {verb} -> {msg[:160]!r}')
        if it is not None and ('Nothing happens' in msg or 'You wrest' in msg):
            agent.inventory.empty_wands.add(it.text)
        if name == 'sleep':
            now = agent.blstats.time
            for m, _ in hits:
                mname = getattr(m[3], 'mname', '?')
                if f'hits the {mname}' in msg:
                    self.slept[(int(m[1]), int(m[2]))] = (mname, now)
        agent.inventory.items.update(force=True)

    def _act_ring(self, plan):
        verb, it, why = plan
        agent = self.agent
        inv = agent.inventory
        self.ring_tries[it.glyphs[0]] = agent.blstats.time
        agent.log(f'WIZ_RING {verb} {it.text!r} ({why})')
        if verb == 'puton':
            ok = inv.put_on(it)
            from .item import ring_amulet_config as rcfg
            if ok and it.object.name not in rcfg.ALWAYS_WEAR_RINGS:
                # ours to take off: the module's hunger shedding (Hungry) would fight our put on every turn
                getattr(inv, '_module_worn', set()).discard(it.glyphs[0])
            if ok and it.object.name == 'regeneration':
                self.regen_glyph = it.glyphs[0]
        else:
            ok = inv.remove_ring_or_amulet(it)
            if ok:
                self.regen_glyph = None
        agent.log(f'WIZ_RING {verb} -> ok={ok} {(agent.message or "")[:100]!r}')

    def strategy(self):
        from .strategy import Strategy

        def f():
            if not (jf_config.WIZ_WAND_FIGHT or jf_config.WIZ_SPEED_SELF or jf_config.WIZ_KIT_BOOST or
                    jf_config.WIZ_RING_SAFE or jf_config.MON_SLEEP_FIGHT):
                yield False
                return
            agent = self.agent
            plan = self._safe(self.fight_plan)
            if plan is not None and not self._blocked((plan[0], plan[2], plan[3])):
                yield True
                self._act_fight(plan)
                return
            plan = self._safe(self.kill_plan)
            if plan is not None and not self._blocked(('melee', plan[1])):
                yield True
                (y, x), name = plan[1], plan[2]
                if not agent._keep_digging_tool_wielded() and agent.wield_best_melee_weapon():
                    return
                agent.log(f'WIZ_KIT hitting the sleeping {name} at ({y},{x})')
                agent.melee_attack(y, x)
                return
            plan = self._safe(self.speed_plan)
            if plan is not None:
                yield True
                self.speed_done = True
                agent.log(f'WIZ_SPEED zapping {plan[1].text!r} at ourselves')
                agent.zap(plan[1], '.')
                agent.log(f'WIZ_SPEED -> {(agent.message or "")[:120]!r}')
                agent.inventory.items.update(force=True)
                return
            plan = self._safe(self.ring_plan)
            if plan is not None and not self._blocked(('ring', plan[0], plan[1].glyphs[0])):
                yield True
                self._act_ring(plan)
                return
            plan = self._safe(self.boost_plan)
            if plan is not None and not self._blocked(('boost', plan[1].text)):
                yield True
                verb, it, name = plan
                self.boosts[it.text] = self.boosts.get(it.text, 0) + 1
                agent.log(f'WIZ_BOOST {verb} {it.text!r}')
                if verb == 'quaff':
                    agent.inventory.quaff(it)
                else:
                    self.mino._read(it, f'WIZ_BOOST {name}')
                agent.log(f'WIZ_BOOST -> {(agent.message or "")[:120]!r}')
                agent.inventory.items.update(force=True)
                return
            yield False

        return Strategy(f)
