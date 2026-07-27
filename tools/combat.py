"""StarCraft / Brood War combat (damage) reference oracle.

An independent second implementation of the BW damage calculation, for the
OpenBW engine to diff against (the VP8-vs-libvpx pattern: our number is worth
something only because it was derived separately).

Two provenance tiers, kept strictly apart (CLAUDE.md rule "measure, never
assume"):

  * MEASURED — every numeric INPUT comes straight from the .dat bytes via
    tools/dat.py: weapon damage_amount / damage_bonus / weapon_type / cooldown,
    a unit's ground/air weapon id + hit count, its subunit (turret) weapon, and
    the target's unit_size / armor / shields. These are byte-facts; the oracle
    tests pin the well-known ones (Marine 6, Zealot 8x2, Firebat 8x3, ...).

  * DOCUMENTED MODEL — the damage-type x unit-size factor table (Normal
    100/100/100, Concussive 100/50/25, Explosive 50/75/100 for S/M/L; shields
    100%, ignore armor; buildings count as Large) is the mechanic published in
    the official StarCraft Compendium (classic.battle.net/scc, attributed in
    assets/combat_reference.json), CROSS-CHECKED to reproduce the compendium's
    own worked examples. The one thing NOT yet byte-verified against a live
    engine is the ARITHMETIC ORDER (armor subtracted per hit, THEN the size
    factor) and BW's fixed-point rounding / minimum-damage floor. That is
    exactly what the engine diff resolves; `breakdown()` exposes every
    intermediate so a mismatch localises to a single step, and the order is
    flagged here rather than hidden.

CLI:  py tools/combat.py [BW_dir]   -> prints the anchor unit table.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dat  # noqa: E402

# ---- sentinels (measured: weapons.dat has 130 entries 0..129, units.dat 228) --
NO_WEAPON = 130          # units.dat ground/air_weapon == 130 -> no weapon
NO_SUBUNIT = 228         # units.dat subunit1 == 228 -> no subunit

# ---- weapons.dat.weapon_type / units.dat.unit_size vocab (measured) -----------
DAMAGE_TYPES = {0: 'Independent', 1: 'Explosive', 2: 'Concussive',
                3: 'Normal', 4: 'IgnoreArmor'}
UNIT_SIZES = {0: 'Independent', 1: 'Small', 2: 'Medium', 3: 'Large'}

# ---- DOCUMENTED MODEL: damage-type x target-size factor, percent --------------
# Compendium mechanic. Independent / IgnoreArmor deal full damage to every size;
# IgnoreArmor additionally skips the armor subtraction (see effective()).
SIZE_FACTOR_PCT = {
    'Explosive':   {'Small': 50,  'Medium': 75,  'Large': 100, 'Independent': 100},
    'Concussive':  {'Small': 100, 'Medium': 50,  'Large': 25,  'Independent': 100},
    'Normal':      {'Small': 100, 'Medium': 100, 'Large': 100, 'Independent': 100},
    'IgnoreArmor': {'Small': 100, 'Medium': 100, 'Large': 100, 'Independent': 100},
    'Independent': {'Small': 100, 'Medium': 100, 'Large': 100, 'Independent': 100},
}


def size_factor_pct(weapon_type, target_size):
    """Percent of per-hit damage the target's size lets through (documented)."""
    wt = weapon_type if isinstance(weapon_type, str) else DAMAGE_TYPES.get(weapon_type, 'Normal')
    sz = target_size if isinstance(target_size, str) else UNIT_SIZES.get(target_size, 'Large')
    return SIZE_FACTOR_PCT.get(wt, SIZE_FACTOR_PCT['Normal']).get(sz, 100)


class CombatModel:
    """Reads units.dat + weapons.dat; resolves a unit's real weapon(s) and
    computes effective damage against any target. Names need stat_txt.tbl."""

    def __init__(self, units, weapons, stat_txt=None):
        self.u = units          # dat.DatFile('units.dat')
        self.w = weapons        # dat.DatFile('weapons.dat')
        self.stat = stat_txt    # tbl.Tbl or None

    # -- construction helpers --------------------------------------------------
    @classmethod
    def from_chain(cls, mpq_chain):
        units = dat.load_from_chain(mpq_chain, 'units.dat')
        weapons = dat.load_from_chain(mpq_chain, 'weapons.dat')
        stat = None
        try:
            import tbl
            stat = tbl.load(mpq_chain.read('rez\\stat_txt.tbl'))
        except Exception:
            stat = None
        return cls(units, weapons, stat)

    # -- names -----------------------------------------------------------------
    def unit_name(self, uid):
        return self.stat.text(uid) if self.stat else 'unit#%d' % uid

    def weapon_name(self, wid):
        if not self.stat:
            return 'weapon#%d' % wid
        label = self.w.get('label', wid)
        return self.stat.text(label - 1) if label else 'weapon#%d' % wid

    # -- weapon description (MEASURED from the .dat bytes) ----------------------
    def weapon_info(self, wid):
        if wid is None or wid >= self.w.count:
            return None
        wt = self.w.get('weapon_type', wid)
        return {
            'weapon_id': wid,
            'name': self.weapon_name(wid),
            'damage': self.w.get('damage_amount', wid),
            'bonus': self.w.get('damage_bonus', wid),
            'type': DAMAGE_TYPES.get(wt, wt),
            'type_id': wt,
            'factor': self.w.get('damage_factor', wid),
            'cooldown': self.w.get('weapon_cooldown', wid),
        }

    def unit_weapons(self, uid):
        """Every attack a unit has, following its subunit (turret) when the base
        unit carries no weapon of its own (Siege Tank / Goliath). Returns a list
        of {mode, hits, host, ...weapon_info}."""
        out = []
        for mode, wfield, hfield in (('ground', 'ground_weapon', 'max_ground_hits'),
                                     ('air', 'air_weapon', 'max_air_hits')):
            wid = self.u.get(wfield, uid)
            host = uid
            if wid == NO_WEAPON:
                sub = self.u.get('subunit1', uid)
                if sub is not None and sub != NO_SUBUNIT:
                    swid = self.u.get(wfield, sub)
                    if swid != NO_WEAPON:
                        wid, host = swid, sub
            if wid == NO_WEAPON:
                continue
            info = self.weapon_info(wid)
            if info is None:
                continue
            hits = self.u.get(hfield, host) or 1
            info = dict(info, mode=mode, hits=hits, host=host)
            out.append(info)
        return out

    # -- target description (MEASURED) -----------------------------------------
    def target_info(self, uid):
        size_id = self.u.get('unit_size', uid)
        shield_amt = self.u.display('shield_amount', uid) if self.u.get('shield_enable', uid) else 0
        return {
            'unit_id': uid,
            'name': self.unit_name(uid),
            'size': UNIT_SIZES.get(size_id, size_id),
            'size_id': size_id,
            'armor': self.u.get('armor', uid),
            'hp': self.u.display('hitpoints', uid),
            'shields': shield_amt,
        }

    # -- the calculation -------------------------------------------------------
    def breakdown(self, weapon_id, hits, target_id, weapon_upgrade=0,
                  armor_upgrade=0, vs_shields=False):
        """Full per-hit -> total breakdown, every intermediate exposed so an
        engine diff localises to a single step.

        MODEL (order flagged above): per hit, take the upgraded weapon damage,
        subtract effective armor (unless the target's plasma shield is taking
        the hit, or the weapon IgnoreArmor), clamp at 0, then apply the size
        factor; multiply by the hit count. Shields take the full size factor of
        Normal (100%) and ignore armor -- 'shields always take 100%'."""
        w = self.weapon_info(weapon_id)
        t = self.target_info(target_id)
        per_hit_base = w['damage'] + w['bonus'] * weapon_upgrade

        if vs_shields and t['shields'] > 0:
            eff_armor = 0
            factor = 100
            armored = per_hit_base            # shields ignore armor
        else:
            if w['type'] == 'IgnoreArmor':
                eff_armor = 0
            else:
                eff_armor = t['armor'] + armor_upgrade
            armored = per_hit_base - eff_armor
            if armored < 0:
                armored = 0
            factor = size_factor_pct(w['type'], t['size'])

        per_hit_eff = armored * factor / 100.0
        total = per_hit_eff * hits
        return {
            'weapon': w['name'], 'weapon_id': weapon_id, 'type': w['type'],
            'target': t['name'], 'target_id': target_id,
            'target_size': t['size'], 'target_armor': t['armor'],
            'vs_shields': bool(vs_shields and t['shields'] > 0),
            'per_hit_base': per_hit_base,
            'effective_armor': eff_armor,
            'after_armor': armored,
            'size_factor_pct': factor,
            'per_hit_effective': per_hit_eff,
            'hits': hits,
            'total_effective': total,
        }

    def effective(self, weapon_id, hits, target_id, **kw):
        """Just the total effective damage per attack (all hits)."""
        return self.breakdown(weapon_id, hits, target_id, **kw)['total_effective']


# ---- reference-file emitter (assets/combat_reference.json) --------------------
def reference_dict():
    """The documented-model tables + ability energy costs, for committing as
    assets/combat_reference.json (the engine's static combat reference)."""
    return {
        'damage_types': DAMAGE_TYPES,
        'unit_sizes': UNIT_SIZES,
        'size_factor_percent': SIZE_FACTOR_PCT,
        'shields': {'factor_percent': 100, 'ignores_armor': True,
                    'note': "plasma shields always take the full (Normal) "
                            "factor and are not reduced by unit armor"},
        'buildings_count_as': 'Large',
        'model': {
            'order': 'per hit: (weapon_damage + bonus*upgrade) - effective_armor '
                     '(clamp >=0), then * size_factor%, then * hits',
            'armor': 'subtracted PER HIT -> multi-hit weapons (Firebat 3, '
                     'Zealot/Goliath-air 2) lose more to armor',
            'ignore_armor_type': 'weapon_type 4 (IgnoreArmor) skips the armor step',
            'independent_type': 'weapon_type 0 (Independent) and IgnoreArmor deal '
                                '100% to every size',
            'unverified': 'the armor->factor ORDER and BW fixed-point rounding / '
                          'minimum-damage floor are the documented model, to be '
                          'confirmed by the engine diff; a fully-absorbed hit '
                          'reads 0 here (BW has a small fixed-point floor)',
        },
        # Ability energy costs (Compendium; future techdata.dat cross-check)
        'ability_energy': {
            'Stim Packs': 0, 'Yamato Gun': 150, 'Lockdown': 100,
            'EMP Shockwave': 100, 'Defensive Matrix': 100, 'Irradiate': 75,
            'Scanner Sweep': 50, 'Cloak (Ghost/Wraith)': 25, 'Nuclear Strike': 0,
            'Psionic Storm': 75, 'Hallucination': 100, 'Stasis Field': 100,
            'Recall': 150, 'Feedback': 50, 'Maelstrom': 100,
            'Mind Control': 150, 'Disruption Web': 125,
            'Spawn Broodlings': 150, 'Dark Swarm': 100, 'Plague': 150,
            'Ensnare': 75, 'Parasite': 75, 'Consume': 0, 'Infestation': 0,
        },
        'attribution': "damage-type x size mechanic and ability energy from the "
                       "official StarCraft Compendium (classic.battle.net/scc); "
                       "all numeric weapon/unit inputs are read from the game's "
                       "own units.dat / weapons.dat by tools/dat.py",
    }


def combat_fixture(model, armors=(0, 1, 2, 3), upgrades=(0, 1, 2, 3)):
    """A deterministic golden fixture the engine's damage code diffs against: for
    every unit that has a weapon (following the turret subunit), the resolved
    attack(s) and the EFFECTIVE per-attack damage over a matrix of target size
    (Small/Medium/Large + Shields), target armor, and weapon-upgrade level.

    Unlike combat_reference.json (the documented factor TABLE), this is the
    concrete number matrix — so a `combatcheck` in the engine can byte-diff its
    native damage output against an independent second implementation. JSON is
    sorted / stable so the committed file only changes when a real number does."""
    SIZES = ('Small', 'Medium', 'Large')
    units = {}
    for uid in range(model.u.count):
        attacks = model.unit_weapons(uid)
        if not attacks:
            continue
        rows = []
        for w in attacks:
            vs = {}
            for size in SIZES:
                cell = {}
                for a in armors:
                    for up in upgrades:
                        cell['a%d_u%d' % (a, up)] = _effective_for(model, w, size, a, up, False)
                vs[size] = cell
            # shields: full factor, ignore armor -> only upgrade varies
            vs['Shields'] = {'u%d' % up: _effective_for(model, w, 'Shields', 0, up, True)
                             for up in upgrades}
            rows.append({'mode': w['mode'], 'weapon': w['name'], 'weapon_id': w['weapon_id'],
                         'type': w['type'], 'hits': w['hits'], 'host': w['host'], 'vs': vs})
        units[str(uid)] = {'name': model.unit_name(uid), 'attacks': rows}
    return {
        'meta': {
            'description': 'per-unit effective damage matrix (independent BW damage '
                           'reference for the engine to diff against)',
            'axes': {'size': list(SIZES) + ['Shields'], 'armor': list(armors),
                     'weapon_upgrade': list(upgrades)},
            'formula': '(damage+bonus*upg - armor, clamp>=0) * sizefactor% * hits; '
                       'shields take 100% and ignore armor',
            'unverified': 'armor->factor order + BW fixed-point rounding / min-damage '
                          'floor (see combat.py) — the engine diff confirms these',
        },
        'units': units,
    }


def _effective_for(model, w, size, armor, weapon_upgrade, vs_shields):
    """Effective damage for a resolved weapon vs a synthetic (size, armor) target,
    computed straight from the documented model (independent of any real unit)."""
    per_hit_base = w['damage'] + w['bonus'] * weapon_upgrade
    if vs_shields:
        armored = per_hit_base
        factor = 100
    else:
        eff_armor = 0 if w['type'] == 'IgnoreArmor' else armor
        armored = max(0, per_hit_base - eff_armor)
        factor = size_factor_pct(w['type'], size)
    return armored * factor / 100.0 * w['hits']


def _fmt(bd):
    tail = ' (vs shields)' if bd['vs_shields'] else ''
    return ('%-18s %-10s vs %-20s [%s a%d]: %d-%d x%d/hit = %g%s'
            % (bd['weapon'], bd['type'], bd['target'], bd['target_size'],
               bd['target_armor'], bd['per_hit_base'], bd['after_armor'],
               bd['hits'], bd['total_effective'], tail))


if __name__ == '__main__':
    import mpq
    import os
    base = sys.argv[1] if len(sys.argv) > 1 else r'C:\Git\Starcraft BroodWar  v1.1.61'
    ch = mpq.MpqChain(base)
    m = CombatModel.from_chain(ch)
    # --fixture: (re)generate assets/combat_fixture.json (the engine's diff target)
    if '--fixture' in sys.argv:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = os.path.join(root, 'assets', 'combat_fixture.json')
        js = json.dumps(combat_fixture(m), indent=1, sort_keys=True, ensure_ascii=False)
        open(out, 'w', encoding='utf-8').write(js)
        print('wrote %s (%d units, %d B)'
              % (out, len(json.loads(js)['units']), len(js.encode('utf-8'))))
        sys.exit(0)
    print('=== anchor attackers (weapon resolved incl. turret subunit) ===')
    for uid in (0, 32, 65, 66, 2, 5, 3, 1):
        for w in m.unit_weapons(uid):
            host = '' if w['host'] == uid else ' (turret %d)' % w['host']
            print('%-16s %-6s %-18s %s dmg=%d x%d%s'
                  % (m.unit_name(uid), w['mode'], w['name'], w['type'],
                     w['damage'], w['hits'], host))
    print('\n=== worked examples (documented factor table) ===')
    # Firebat (Concussive 8, 3 hits) vs sizes; armor cost of multi-hit
    fb = [w for w in m.unit_weapons(32) if w['mode'] == 'ground'][0]
    for tid in (0, 65, 66):   # Marine(S,0) Zealot(S,1) Dragoon(L,1)
        print(_fmt(m.breakdown(fb['weapon_id'], fb['hits'], tid)))
    # Dragoon (Explosive 20) vs sizes
    dg = [w for w in m.unit_weapons(66) if w['mode'] == 'ground'][0]
    for tid in (0, 2, 66):    # Marine(S) Vulture(M) Dragoon(L)
        print(_fmt(m.breakdown(dg['weapon_id'], dg['hits'], tid)))
    if len(sys.argv) > 2 and sys.argv[2] == '--json':
        print(json.dumps(reference_dict(), indent=2))
