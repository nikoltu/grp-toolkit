#!/usr/bin/env python3
"""Tech and upgrade id -> name tables for replay analysis.

Borrowed format-data (like the AI/iscript opcode names): the tech and upgrade
name lists come from screp (github.com/icza/screp, MIT (c) Andras Belicza). Unit
type ids are NOT here - those resolve through the install's stat_txt.tbl, the
same measured path the DAT tools use. Tech/upgrade ids are stable BW constants.
"""

TECHS = {
    0x00: 'Stim Packs', 0x01: 'Lockdown', 0x02: 'EMP Shockwave', 0x03: 'Spider Mines',
    0x04: 'Scanner Sweep', 0x05: 'Tank Siege Mode', 0x06: 'Defensive Matrix',
    0x07: 'Irradiate', 0x08: 'Yamato Gun', 0x09: 'Cloaking Field',
    0x0A: 'Personnel Cloaking', 0x0B: 'Burrowing', 0x0C: 'Infestation',
    0x0D: 'Spawn Broodlings', 0x0E: 'Dark Swarm', 0x0F: 'Plague', 0x10: 'Consume',
    0x11: 'Ensnare', 0x12: 'Parasite', 0x13: 'Psionic Storm', 0x14: 'Hallucination',
    0x15: 'Recall', 0x16: 'Stasis Field', 0x17: 'Archon Warp', 0x18: 'Restoration',
    0x19: 'Disruption Web', 0x1B: 'Mind Control', 0x1C: 'Dark Archon Meld',
    0x1D: 'Feedback', 0x1E: 'Optical Flare', 0x1F: 'Maelstrom', 0x20: 'Lurker Aspect',
    0x22: 'Healing',
}

UPGRADES = {
    0x00: 'Terran Infantry Armor', 0x01: 'Terran Vehicle Plating',
    0x02: 'Terran Ship Plating', 0x03: 'Zerg Carapace', 0x04: 'Zerg Flyer Carapace',
    0x05: 'Protoss Ground Armor', 0x06: 'Protoss Air Armor',
    0x07: 'Terran Infantry Weapons', 0x08: 'Terran Vehicle Weapons',
    0x09: 'Terran Ship Weapons', 0x0A: 'Zerg Melee Attacks', 0x0B: 'Zerg Missile Attacks',
    0x0C: 'Zerg Flyer Attacks', 0x0D: 'Protoss Ground Weapons',
    0x0E: 'Protoss Air Weapons', 0x0F: 'Protoss Plasma Shields',
    0x10: 'U-238 Shells (Marine Range)', 0x11: 'Ion Thrusters (Vulture Speed)',
    0x13: 'Titan Reactor (Science Vessel Energy)', 0x14: 'Ocular Implants (Ghost Sight)',
    0x15: 'Moebius Reactor (Ghost Energy)', 0x16: 'Apollo Reactor (Wraith Energy)',
    0x17: 'Colossus Reactor (Battlecruiser Energy)', 0x18: 'Ventral Sacs (Overlord Transport)',
    0x19: 'Antennae (Overlord Sight)', 0x1A: 'Pneumatized Carapace (Overlord Speed)',
    0x1B: 'Metabolic Boost (Zergling Speed)', 0x1C: 'Adrenal Glands (Zergling Attack)',
    0x1D: 'Muscular Augments (Hydralisk Speed)', 0x1E: 'Grooved Spines (Hydralisk Range)',
    0x1F: 'Gamete Meiosis (Queen Energy)', 0x20: 'Defiler Energy',
    0x21: 'Singularity Charge (Dragoon Range)', 0x22: 'Leg Enhancement (Zealot Speed)',
    0x23: 'Scarab Damage', 0x24: 'Reaver Capacity', 0x25: 'Gravitic Drive (Shuttle Speed)',
    0x26: 'Sensor Array (Observer Sight)', 0x27: 'Gravitic Booster (Observer Speed)',
    0x28: 'Khaydarin Amulet (Templar Energy)', 0x29: 'Apial Sensors (Scout Sight)',
    0x2A: 'Gravitic Thrusters (Scout Speed)', 0x2B: 'Carrier Capacity',
    0x2C: 'Khaydarin Core (Arbiter Energy)', 0x2F: 'Argus Jewel (Corsair Energy)',
    0x31: 'Argus Talisman (Dark Archon Energy)', 0x33: 'Caduceus Reactor (Medic Energy)',
    0x34: 'Chitinous Plating (Ultralisk Armor)', 0x35: 'Anabolic Synthesis (Ultralisk Speed)',
    0x36: 'Charon Boosters (Goliath Range)',
}


def tech_name(tid):
    return TECHS.get(tid, 'tech %s' % tid)


def upgrade_name(uid):
    return UPGRADES.get(uid, 'upgrade %s' % uid)
