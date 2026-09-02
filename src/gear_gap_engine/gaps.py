"""The deterministic core: which slots are gaps, and where the right item drops.

Stdlib only. Nothing in this module reaches for the network, a database or a
config file, and nothing in it knows which character it is looking at.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

# ------------------------------------------------------------------ vocabulary

# The four rating types. This is deliberately the same vocabulary the Blizzard
# API uses for equipped items AND the one item_stats.json records, so the two
# sides of an identity comparison never need translating at the call site. If
# those ever diverge, the translation belongs at the boundary that changed, not
# here -- and test_engine_vocabulary pins the agreement.
SECONDARY = frozenset({"CRIT_RATING", "HASTE_RATING", "MASTERY_RATING", "VERSATILITY"})

SHORT = {
    "CRIT_RATING": "Crit",
    "HASTE_RATING": "Haste",
    "MASTERY_RATING": "Mastery",
    "VERSATILITY": "Vers",
}

# The slots the Catalyst converts. In these the equipped item id becomes the tier
# item's id whatever went in, so identity has to be recovered from the stats.
CATALYST_SLOTS = frozenset({"head", "shoulder", "chest", "hands", "legs"})

# A guide's slot label -> the canonical slot key. None means the slot is paired.
BIS_SLOT_TO_SLOT: Mapping[str, str | None] = {
    "helm": "head",
    "head": "head",
    "neck": "neck",
    "shoulders": "shoulder",
    "cloak": "back",
    "back": "back",
    "chest": "chest",
    "waist": "waist",
    "bracers": "wrist",
    "hands": "hands",
    "legs": "legs",
    "feet": "feet",
    "ring": None,
    "trinket": None,
    "main hand": "mainhand",
    "off hand": "offhand",
}

# Only rings and trinkets are paired. Anything else mapping to None would fall
# into the pairing branch and end up compared against a trinket, which is how a
# Protection Paladin's shield was once measured against one.
# Every playable class, as the slug that ends a spec key. ONE authority, in the
# pure layer, because two mechanisms for "which class is this spec" is how they
# disagree -- and they did.
#
# The builder splits discovered slugs with this ("blood-death-knight" ->
# "death-knight"), and the roster reads it to decide which of the bundle's specs
# a character may be added as. It used to be declared in the builder and
# INFERRED separately at runtime, as "any suffix shared by two or more spec
# keys". That inference is only correct on a bundle carrying several specs per
# class: the default build carries ONE per class, no suffix repeats, and it
# returned nothing -- so the roster's "add from your account" list was empty from
# the day it shipped.
#
# A declared list is game data in code, which this project avoids. It is here
# anyway because the alternative was worse and because the exposure already
# existed: a class missing from this tuple makes the builder skip that class's
# specs silently, so the list was already a single point of failure. It is now
# one point of failure instead of one plus a wrong guess.
CLASS_SLUGS: tuple[str, ...] = (
    "death-knight", "demon-hunter", "evoker", "druid", "hunter", "mage", "monk",
    "paladin", "priest", "rogue", "shaman", "warlock", "warrior",
)


def class_of(spec_key: str) -> str | None:
    """Which class a spec key belongs to, or None if it names no known class.

    LONGEST match, because the false positives are always shorter:
    `havoc-demon-hunter` ends with `-hunter` and is not a Hunter spec, and
    `blood-death-knight` ends with `-knight`.

    Depends only on the key and the class list -- never on how many specs are
    being considered, which is exactly what the old inference got wrong.
    """
    matches = [s for s in CLASS_SLUGS if spec_key.endswith(f"-{s}")]
    return max(matches, key=len) if matches else None


PAIRED: Mapping[str, tuple[str, str]] = {
    "ring": ("finger1", "finger2"),
    "trinket": ("trinket1", "trinket2"),
}

PROFESSIONS = (
    "Blacksmithing",
    "Leatherworking",
    "Jewelcrafting",
    "Tailoring",
    "Alchemy",
    "Enchanting",
    "Inscription",
    "Engineering",
)

Reason = Literal["empty", "below_chest_ilvl", "wrong_item", "wrong_base", "unverifiable"]

REASONS: Mapping[str, str] = {
    "empty": "nothing equipped in this slot",
    "below_chest_ilvl": "under what a key end-of-run chest drops",
    "wrong_item": "not the item the guide names for this slot",
    "wrong_base": "converted from the wrong base, so the stats are stuck",
    "unverifiable": "converted slot with no cached stats for the guide pick",
}

SourceKind = Literal["dungeon", "raid", "craft", "catalyst", "vault", "unknown"]

# A source the guide names that is neither a place nor a profession.
#
# "Catalyst" alone is a conversion whose base the guide does not locate -- 17 M+
# picks across the published specs say only that. "The Great Vault" is the weekly
# chest. Both are real answers to "where does this come from" and neither is
# farmable, so both are REPORTED AND NEVER ROUTED, exactly as a raid is: hiding
# the gap would make the tool lie about the slot, and routing it would send
# someone somewhere they cannot go.
GREAT_VAULT = "The Great Vault"
CATALYST = "Catalyst"

# The shortest source name that may be matched by containment. Guards the
# two-way test below from firing on a fragment.
_MIN_MATCH = 6

# Anything assess() can return. A paired slot is one row about two slots.



# ----------------------------------------------------------------------- types


@dataclass(frozen=True, slots=True)
class EquippedItem:
    """One equipped piece, as the engine needs it."""

    slot: str
    item_id: int
    name: str
    ilvl: int
    is_set_piece: bool = False
    secondaries: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BisEntry:
    """One row of a guide's list for a spec."""

    slot_label: str
    item_id: int
    name: str
    source: str | None = None
    catalyst_input: int | None = None
    gems: Sequence[str] = ()

    @property
    def wanted_id(self) -> int:
        """The item to actually obtain.

        On a Catalyst row the card is titled with the tier item while the thing
        that drops is the base, so the base wins wherever the guide names one.
        """
        return self.catalyst_input or self.item_id


@dataclass(frozen=True, slots=True)
class SpecReference:
    """One spec's slice of the reference bundle."""

    mythic_bis: Sequence[BisEntry] = ()
    trinket_tiers: Mapping[str, Mapping[str, Sequence[str]]] = field(default_factory=dict)

    def trinket_tier(self, name: str) -> str | None:
        for tier, by_content in self.trinket_tiers.items():
            for names in by_content.values():
                if name in names:
                    return tier
        return None


@dataclass(frozen=True, slots=True)
class ItemStats:
    """Cached secondaries per item id, keyed as strings the way the bundle is."""

    items: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def get(self, item_id: int) -> Mapping[str, Any] | None:
        return self.items.get(str(item_id))


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Where an item comes from, classified."""

    kind: SourceKind
    name: str | None
    catalyst: bool


@dataclass(frozen=True, slots=True)
class Target:
    """One item to go and get.

    Every list the tool produces -- the route, the crafts, the raid rows -- is
    built out of these, so a single slot and a paired slot cannot disagree about
    what a target is.
    """

    bis_slot: str
    want: str
    want_id: int
    farm: str | None
    becomes: str | None
    source: str | None
    source_kind: SourceKind
    catalyst: bool
    want_roll: str | None
    # What the guide sockets in this item. Carried on the target because a craft
    # is an instruction -- "get this made, with these" -- and the gems are half
    # of it. The spec asks for them and the bundle has held them since the
    # builder was written; nothing was reading them.
    gems: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "bis_slot": self.bis_slot,
            "want": self.want,
            "want_id": self.want_id,
            "farm": self.farm,
            "becomes": self.becomes,
            "source": self.source,
            "source_kind": self.source_kind,
            "catalyst": self.catalyst,
            "want_roll": self.want_roll,
            "gems": list(self.gems),
        }


@dataclass(frozen=True, slots=True)
class HeldItem:
    """One equipped piece of a pair, as the page shows it."""

    slot: str
    name: str
    ilvl: int
    roll: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"slot": self.slot, "name": self.name, "ilvl": self.ilvl, "roll": self.roll}


@dataclass(frozen=True, slots=True)
class PairRow:
    """A paired slot, compared as a set (ADR 006).

    Rings and trinkets are the only paired slots, and comparing them entry by
    entry cannot work. Matching each guide entry against the weaker of the two
    equipped items reported a ring the character was wearing as a gap. Matching
    a worn guide item first and then comparing the remainder fixes that one case
    but leaves a sequencing problem: when the guide names two and the character
    holds neither, farming the first replaces the weaker item and the second then
    has to replace the stronger one, so the two entries cannot both measure
    against the same slot.

    A set has no "which ring does this row replace" to get wrong. The character's
    pair is matched against the guide's pair, and the result is one finding
    naming what is missing and where it drops.
    """

    bis_slot: str
    slot_keys: tuple[str, ...]
    held: tuple[HeldItem, ...]
    named: int
    matched: tuple[str, ...]
    missing: tuple[Target, ...]
    improvable: bool

    @property
    def reasons(self) -> tuple[str, ...]:
        # A pair carries no reason codes. What is wrong with it is "you hold N of
        # M", which the row states directly; a code would be a second way of
        # saying the same thing.
        return ()

    @property
    def is_gap(self) -> bool:
        """A pair is a gap when it has something ACTIONABLE outstanding.

        Defined in terms of targets rather than beside them, because the two
        drifting apart is what hid the defect: find_gaps() filters on is_gap, so
        a pair that was not a gap never reached crafts() however carefully
        targets was written.
        """
        return bool(self.targets)

    @property
    def targets(self) -> tuple[Target, ...]:
        """What to go and get for this pair.

        The reachability gate is applied PER TARGET, not to the pair. It asks
        whether a key's chest could beat what is worn, which is a statement
        about dungeon drops and says nothing about a craft: a crafted item does
        not come out of a key and is obtainable at any item level, at any time.

        Gating the whole pair on it hid a real gap -- a reader wearing two rings
        above the chest still does not own the ring the guide names, and can go
        and have it made. Lifting the gate for the whole pair was the other
        mistake: that let the pair's DUNGEON want back into the route, which is
        the rule that keeps a 311 drop off a 334 slot.
        """
        if self.improvable:
            return self.missing
        return tuple(t for t in self.missing if t.source_kind == "craft")

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "pair",
            "slot": None,
            "bis_slot": self.bis_slot,
            "slots": list(self.slot_keys),
            "reasons": [],
            "held": [h.as_dict() for h in self.held],
            "named": self.named,
            "matched": list(self.matched),
            "missing": [t.as_dict() for t in self.missing],
            "improvable": self.improvable,
        }


@dataclass(frozen=True, slots=True)
class GapRow:
    """One row of the output contract, gap or not.

    An empty `reasons` means the slot already holds the item the guide names.

    slot is None for a paired slot.

    identity and reachable are separate on purpose (ADR 005). identity is whether
    this is the item the guide names, tested for every slot. reachable is whether
    a key's chest could improve the slot at all. Only reachable slots contribute
    an identity finding to reasons, so the gap list and the route are decided by
    reachability exactly as before -- but the page can now tell a slot that holds
    the guide's pick apart from one that merely sits above anything farmable.
    """

    slot: str | None
    bis_slot: str
    reasons: tuple[str, ...]
    identity: Literal["yes", "no", "unknown"]
    reachable: bool
    want: str
    want_id: int
    farm: str | None
    becomes: str | None
    source: str | None
    source_kind: SourceKind
    catalyst: bool
    have: str | None
    have_ilvl: int | None
    have_roll: str | None
    want_roll: str | None
    # Defaulted so every existing construction keeps working: gems are extra
    # detail on a target, never part of what makes a slot a gap.
    gems: tuple[str, ...] = ()

    @property
    def is_gap(self) -> bool:
        return bool(self.reasons)

    @property
    def targets(self) -> tuple[Target, ...]:
        """A single slot is at most one target, and only when it is a gap."""
        if not self.is_gap:
            return ()
        return (
            Target(
                bis_slot=self.bis_slot,
                want=self.want,
                want_id=self.want_id,
                farm=self.farm,
                becomes=self.becomes,
                source=self.source,
                source_kind=self.source_kind,
                catalyst=self.catalyst,
                want_roll=self.want_roll,
                gems=self.gems,
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "slot",
            "slot": self.slot,
            "bis_slot": self.bis_slot,
            "reasons": list(self.reasons),
            "identity": self.identity,
            "reachable": self.reachable,
            "want": self.want,
            "want_id": self.want_id,
            "farm": self.farm,
            "becomes": self.becomes,
            "source": self.source,
            "source_kind": self.source_kind,
            "catalyst": self.catalyst,
            "have": self.have,
            "have_ilvl": self.have_ilvl,
            "have_roll": self.have_roll,
            "want_roll": self.want_roll,
        }


# -------------------------------------------------------------------- identity


def fingerprint(secondaries: Mapping[str, int] | None) -> tuple[tuple[str, float], ...] | None:
    """Secondaries as shares of their own total.

    Each side is normalised against itself, so the comparison is independent of
    both item level and the absolute scale the source reports in: a base read off
    Wowhead at 311 matches the same item crested to 334, and it matches whether
    the numbers arrive tooltip-sized or API-sized. Only the ratio is ever
    compared, never a magnitude.

    ASSUMPTION, verified on three items and no more: the Catalyst preserves the
    base's secondary split exactly, and item level scaling is proportional. If
    Blizzard changes either, this returns confident wrong answers rather than
    failing, which is why the invariance case is pinned by a test.
    """
    if not secondaries:
        return None
    total = sum(secondaries.values())
    if not total:
        return None
    return tuple(
        sorted((k, round(v / total, 2)) for k, v in secondaries.items() if v)
    )


def identify(
    current: EquippedItem | None,
    wanted_id: int,
    slot: str,
    item_stats: ItemStats | None = None,
) -> Literal["yes", "no", "unknown"]:
    """Is the equipped piece the item the guide names?

    Two mechanisms, because the Catalyst destroys one of them.

    By item id wherever the id survives, which covers every unconverted slot and
    needs no reference data. By secondary fingerprint on a converted slot, where
    the id was overwritten with the tier item's and the inherited secondaries are
    the only surviving evidence of what went in.

    "unknown" is a real answer and must never collapse into "yes". It means the
    reference data does not cover this item, not that the slot is fine.
    """
    if current is None:
        return "no"
    if current.item_id == wanted_id:
        return "yes"
    if not (current.is_set_piece and slot in CATALYST_SLOTS):
        return "no"
    reference = item_stats.get(wanted_id) if item_stats else None
    if not reference:
        return "unknown"
    here = fingerprint(current.secondaries)
    there = fingerprint(reference.get("secondaries"))
    if here is None or there is None:
        return "unknown"
    return "yes" if here == there else "no"


def roll_report(secondaries: Mapping[str, int] | None) -> str | None:
    """Secondaries as they are, biggest first. No score attached, by design."""
    if not secondaries:
        return None
    return " / ".join(
        f"{SHORT.get(k, k)} {v}"
        for k, v in sorted(secondaries.items(), key=lambda kv: -kv[1])
    )


# ---------------------------------------------------------------------- slots


MISSING = "MISSING"


def slot_key(bis_slot: str | None) -> str | None:
    """A guide's slot label -> the canonical key.

    None means the slot is paired. MISSING means the label was not recognised,
    which is a bundle problem rather than a slot.
    """
    return BIS_SLOT_TO_SLOT.get((bis_slot or "").strip().lower(), MISSING)


def equipped_for(
    equipped: Mapping[str, EquippedItem], bis_slot: str
) -> EquippedItem | None:
    """The item in the slot a guide entry names.

    Rings and trinkets are paired, so the weaker of the two is the one a drop
    would actually replace.
    """
    key = slot_key(bis_slot)
    if key == MISSING:
        return None
    if key is None:
        pair = PAIRED.get(bis_slot.strip().lower())
        if not pair:
            return None
        held = [equipped[p] for p in pair if p in equipped]
        return min(held, key=lambda i: i.ilvl) if held else None
    return equipped.get(key)


# --------------------------------------------------------------------- source


def _match_key(text: str) -> str:
    """A name reduced to what is stable about it.

    Case, punctuation and a leading article are orthography, not identity. The
    season pool records "Kings' Rest" and the guide writes "King's Rest"; those
    are one dungeon, and a matcher that says otherwise turns every row from it
    into an unclassifiable source.

    Squashing to letters and digits is safe for this pool because no dungeon
    name is a substring of another. That is a property of the data and is
    asserted at load time, not assumed here.
    """
    stripped = re.sub(r"^the\s+", "", text.strip().lower())
    return re.sub(r"[^a-z0-9]+", "", stripped)


class IndistinguishableSources(ValueError):
    """Two source names collapse to the same match key, or one contains another.

    The matcher would classify rows from one as the other, so this is refused at
    load rather than producing confident wrong sources later.
    """


def assert_sources_distinguishable(names: Iterable[str]) -> None:
    """Refuse a source-name set the matcher cannot tell apart.

    PUBLIC BECAUSE THE INVARIANT IS THE ENGINE'S, NOT THE CALLER'S. Matching
    squashes names to letters and digits, which is only safe while no name is a
    substring of another once squashed. The loader used to import the private
    `_match_key` and re-implement this check itself -- which meant the caller had
    to know HOW names are normalised in order to guard an assumption it did not
    own, and pinned a leading-underscore symbol across what is now a package
    boundary.

    Exposing the question instead of the mechanism lets the normalisation change
    without breaking anyone: the check moves with the matcher it protects.

    Raises IndistinguishableSources naming both offenders. Callers that have
    their own error vocabulary catch it and re-raise; the engine does not import
    anybody else's exception type.
    """
    keys = {name: _match_key(name) for name in names}
    for name, key in keys.items():
        for other, other_key in keys.items():
            if name != other and key and key in other_key:
                raise IndistinguishableSources(
                    f"source names are not distinguishable: {name!r} inside {other!r}"
                )


def make_source_parser(
    dungeons: Iterable[str] = (), raids: Iterable[str] = ()
) -> Callable[[str | None], SourceRef]:
    """Classify a guide's source line.

    The distinction is not cosmetic. Only a dungeon can be routed, because only a
    dungeon can be queued repeatedly. A craft is a one-time action, a raid is a
    weekly lockout, the Great Vault is a weekly reward, and a bare Catalyst is a
    conversion with no stated location -- none of those is a farm target, and all
    of them are reported rather than hidden.

    The dungeon and raid lists are season data and are injected, so this stays
    true for any season.

    Order matters. Professions are checked first because "Crafted by
    Blacksmithing" contains no location, but a line can name both a profession
    and a place, and the profession is what decides how the row is acted on.
    Raids come before dungeons for the same reason: a raid line names a boss and
    a zone, and the zone is the part that classifies it. Catalyst is checked
    LAST of all, because "Catalyst from King's Rest" is a dungeon row that
    happens to need converting -- only a Catalyst line naming nowhere is a
    catalyst source.
    """
    dungeon_keys = [(name, _match_key(name)) for name in dungeons]
    raid_keys = [(name, _match_key(name)) for name in raids]
    vault_key = _match_key(GREAT_VAULT)

    def names(source_key: str, pool: list[tuple[str, str]]) -> str | None:
        """Does the source name one of these?

        Containment is tested BOTH WAYS. The guide writes "Vashnik" where the
        season pool has "Vashnik the Malignant", so testing only "pool inside
        source" misses every boss the guide names without its epithet -- and
        testing only the reverse would match a source that merely mentions a
        fragment. The length guard stops the two-way test firing on one.
        """
        for name, key in pool:
            if not key:
                continue
            if key in source_key:
                return name
            if len(source_key) >= _MIN_MATCH and source_key in key:
                return name
            # And the pool name's own leading word inside the source, which is
            # the case the two tests above both miss: "Tier token from Vashnik"
            # neither contains "Vashnik the Malignant" nor sits inside it. The
            # docstring's own example only worked when the guide wrote the short
            # form ALONE. Same length guard, so a leading "The" cannot match.
            lead = _match_key(name.split(" ", 1)[0])
            if len(lead) >= _MIN_MATCH and lead in source_key:
                return name
        return None

    def parse(text: str | None) -> SourceRef:
        raw = text or ""
        catalyst = "catalyst" in raw.lower()
        for profession in PROFESSIONS:
            if profession in raw:
                return SourceRef("craft", profession, catalyst)

        key = _match_key(raw)
        found = names(key, raid_keys)
        if found:
            return SourceRef("raid", found, catalyst)
        found = names(key, dungeon_keys)
        if found:
            # The pool's spelling, not the guide's prose. The season list is
            # what the route and the matrix group by.
            return SourceRef("dungeon", found, catalyst)

        if vault_key and vault_key in key:
            return SourceRef("vault", GREAT_VAULT, catalyst)
        if catalyst:
            # Names the Catalyst and nowhere else: a conversion whose base the
            # guide does not locate.
            return SourceRef("catalyst", CATALYST, True)
        return SourceRef("unknown", raw or None, catalyst)

    return parse


# A stand-in kept in the row list while a pair is still being collected, so the
# finished pair row lands where the guide first named the slot.
_PLACEHOLDER: Any = object()


# ------------------------------------------------------------------ the rules


def assess(
    equipped: Mapping[str, EquippedItem],
    spec_ref: SpecReference,
    item_stats: ItemStats | None = None,
    chest_ilvl: int | None = None,
    source_parser: Callable[[str | None], SourceRef] | None = None,
) -> list[GapRow | PairRow]:
    """Every slot the guide names, gap or not.

    find_gaps() answers "what do I go and do". This answers "how does this
    character stand", which is a different question and needs the satisfied slots
    in it: a view that lists only problems cannot be read as a picture of a set.

    chest_ilvl is what a key's end-of-run chest drops at the level being run, and
    that one number drives every reachability decision below.

    Reasons stack. A slot can be both under the item level ceiling and the wrong
    item, and they are separate findings.
    """
    parse = source_parser or make_source_parser()
    rows: list[GapRow | PairRow] = []
    # Paired entries are collected and resolved as a set once, in the position
    # the guide first names them (ADR 006).
    paired: dict[str, list[BisEntry]] = {}

    for entry in spec_ref.mythic_bis:
        slot = slot_key(entry.slot_label)
        if slot == MISSING:
            continue

        # A trinket outside the guide's S and A tiers is not a target whatever is
        # equipped. The tier list is the guide's opinion, read rather than
        # computed -- ranking trinkets ourselves would need a sim.
        if entry.slot_label.strip().lower() == "trinket":
            tier = spec_ref.trinket_tier(entry.name)
            if tier and tier not in ("S", "A"):
                continue

        if slot is None:
            label = entry.slot_label.strip().lower()
            if label in PAIRED:
                first = label not in paired
                paired.setdefault(label, []).append(entry)
                if first:
                    # Hold the position; the row is built once the whole pair is
                    # known.
                    rows.append(_PLACEHOLDER)
                continue

        source = parse(entry.source)
        current = equipped_for(equipped, entry.slot_label)

        if current is None:
            rows.append(
                _row(entry, slot, ("empty",), source, None, item_stats,
                     identity="no", reachable=True)
            )
            continue

        # A source can only help if what it drops is AT LEAST what is already in
        # the slot. Equal counts, for two reasons: at equal item level the
        # guide's item is the one worth having, and on a Catalyst slot the
        # base's secondaries are permanent, so a lateral re-convert is a real
        # gain. Above it, farming is a downgrade however the stats compare,
        # which is what keeps Myth 334 legs off the list for a 311 dungeon drop.
        # A CRAFT is never gated on this. Reachability asks whether a key's
        # chest could beat what is worn, and a crafted item does not come out of
        # a key -- it is obtainable at any item level, at any time. Gating it on
        # key reachability hid a real, actionable gap behind a rule about
        # dungeons: a reader wearing 340 rings still does not own the ring the
        # guide names, and can go and have it made this afternoon. The spec's
        # rule is that hiding a gap makes the tool lie.
        reachable = (
            source.kind == "craft" or chest_ilvl is None or chest_ilvl >= current.ilvl
        )

        reasons: list[str] = []
        if chest_ilvl is not None and current.ilvl < chest_ilvl:
            reasons.append("below_chest_ilvl")

        # ADR 005: identity is tested for EVERY slot, reachable or not. It costs
        # one pure comparison and cannot change the gap list, because only a
        # reachable slot turns a verdict into a reason. What it buys is that the
        # page can say "holds the guide's pick" rather than "not checked" about a
        # slot nobody could farm anyway -- for a well-geared character that is
        # most of the page, and the by-slot view exists to say how they stand.
        found = identify(current, entry.wanted_id, current.slot, item_stats)

        if reachable:
            if found == "no":
                # A WRONG ITEM IS A GAP EVEN AT THE CEILING. A converted piece's
                # secondaries are permanent, so a slot sitting exactly at the
                # chest item level can still be the wrong item and still needs
                # farming. Item level and identity are separate reasons, never
                # one gate: an earlier version short-circuited on item level here
                # and silently dropped those slots off the route.
                converted = current.slot in CATALYST_SLOTS and current.is_set_piece
                reasons.append("wrong_base" if converted else "wrong_item")
            elif found == "unknown":
                reasons.append("unverifiable")

        rows.append(
            _row(entry, slot, tuple(reasons), source, current, item_stats,
                 identity=found, reachable=reachable)
        )

    # Fill the placeholders in the order the pairs were first named.
    pair_rows = [
        _pair_row(label, entries, equipped, item_stats, chest_ilvl, parse)
        for label, entries in paired.items()
    ]
    filled = iter(pair_rows)
    return [next(filled) if r is _PLACEHOLDER else r for r in rows]


def _target(entry: BisEntry, source: SourceRef, item_stats: ItemStats | None) -> Target:
    reference = item_stats.get(entry.wanted_id) if item_stats else None
    return Target(
        bis_slot=entry.slot_label,
        want=entry.name,
        want_id=entry.wanted_id,
        farm=((reference or {}).get("name") if source.catalyst else entry.name) or None,
        becomes=entry.name if source.catalyst else None,
        source=source.name,
        source_kind=source.kind,
        catalyst=source.catalyst,
        want_roll=roll_report((reference or {}).get("secondaries")) if reference else None,
        gems=tuple(entry.gems),
    )


def _pair_row(
    label: str,
    entries: list[BisEntry],
    equipped: Mapping[str, EquippedItem],
    item_stats: ItemStats | None,
    chest_ilvl: int | None,
    parse: Callable[[str | None], SourceRef],
) -> PairRow:
    """Match a character's pair against the guide's pair.

    Each equipped item satisfies at most one guide entry, so a character wearing
    one of the two named rings is credited with exactly one.
    """
    slot_keys = PAIRED[label]
    held = [equipped[k] for k in slot_keys if k in equipped]

    matched: list[str] = []
    missing: list[Target] = []
    claimed: set[str] = set()

    for entry in entries:
        hit = next(
            (
                h for h in held
                if h.slot not in claimed
                and identify(h, entry.wanted_id, h.slot, item_stats) == "yes"
            ),
            None,
        )
        if hit is not None:
            claimed.add(hit.slot)
            matched.append(entry.name)
        else:
            missing.append(_target(entry, parse(entry.source), item_stats))

    # Something in the pair is worth replacing only if a chest drops at least
    # what one of the worn items is. Deciding this for the pair rather than per
    # entry is what avoids the sequencing problem: there is no need to say which
    # of the two a given drop would replace.
    improvable = not held or chest_ilvl is None or any(h.ilvl <= chest_ilvl for h in held)

    return PairRow(
        bis_slot=entries[0].slot_label,
        slot_keys=slot_keys,
        held=tuple(
            HeldItem(slot=h.slot, name=h.name, ilvl=h.ilvl, roll=roll_report(h.secondaries))
            for h in sorted(held, key=lambda h: h.slot)
        ),
        named=len(entries),
        matched=tuple(matched),
        missing=tuple(missing),
        improvable=improvable,
    )


def _row(
    entry: BisEntry,
    slot: str | None,
    reasons: tuple[str, ...],
    source: SourceRef,
    current: EquippedItem | None,
    item_stats: ItemStats | None,
    *,
    identity: Literal["yes", "no", "unknown"],
    reachable: bool,
) -> GapRow:
    reference = item_stats.get(entry.wanted_id) if item_stats else None
    return GapRow(
        slot=slot,
        bis_slot=entry.slot_label,
        reasons=reasons,
        identity=identity,
        reachable=reachable,
        # want is what the slot ends up as; want_id is what you go and get. On a
        # Catalyst row those are different items, which is why farm and becomes
        # are separate: "farm Warhelm of the Consecrated Flame" is an instruction
        # nobody can follow, because it does not drop anywhere.
        want=entry.name,
        want_id=entry.wanted_id,
        farm=((reference or {}).get("name") if source.catalyst else entry.name) or None,
        becomes=entry.name if source.catalyst else None,
        source=source.name,
        source_kind=source.kind,
        catalyst=source.catalyst,
        have=current.name if current else None,
        have_ilvl=current.ilvl if current else None,
        have_roll=roll_report(current.secondaries) if current else None,
        want_roll=roll_report((reference or {}).get("secondaries")) if reference else None,
        gems=tuple(entry.gems),
    )


def find_gaps(
    equipped: Mapping[str, EquippedItem],
    spec_ref: SpecReference,
    item_stats: ItemStats | None = None,
    chest_ilvl: int | None = None,
    source_parser: Callable[[str | None], SourceRef] | None = None,
) -> list[GapRow | PairRow]:
    """The subset of assess() that needs action. Same rules, gaps only."""
    return [row for row in assess(equipped, spec_ref, item_stats, chest_ilvl, source_parser)
            if row.is_gap]


# ------------------------------------------------------------- the three lists


def targets_of(rows: Iterable[GapRow | PairRow]) -> list[Target]:
    """Every item to go and get, flattened.

    One slot yields at most one; a pair yields one per missing item. The three
    lists below are all built from this, so they can never disagree about what a
    target is.
    """
    return [target for row in rows for target in row.targets]


def route(gaps: Iterable[GapRow | PairRow]) -> dict[str, list[dict[str, Any]]]:
    """Dungeon gaps grouped by dungeon, most gaps first. What to queue.

    Nothing more than counting: the dungeon that closes the most slots sorts
    first. Only dungeon sources appear, because only a dungeon can be queued.

    An empty route beside a non-empty gap list is a real state, not an error: it
    means there is nothing left in keys for this character.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    # targets_of() filters on is_gap rather than trusting the caller. This
    # function is documented as taking gaps and production only ever passes
    # find_gaps() output, but handed assess() output it would otherwise route
    # slots that are already right -- a silent wrong answer rather than an error.
    for target in targets_of(gaps):
        if target.source_kind != "dungeon" or not target.source:
            continue
        grouped.setdefault(target.source, []).append(
            {
                "item": target.want,
                "id": target.want_id,
                "slot": target.bis_slot,
                "catalyst": target.catalyst,
            }
        )
    return dict(sorted(grouped.items(), key=lambda kv: -len(kv[1])))


def crafts(
    gaps: Iterable[GapRow | PairRow], order: Sequence[str] | None = None
) -> list[Target]:
    """Craft targets, in the guide's crafting order.

    A craft is an action, not a farm target: you have the item or you go get it
    made, so it never appears in a route. The order matters because crafting
    resources are scarce early in a season the same way Catalyst charges are, and
    the guide gives an explicit one per spec.

    Anything the order does not name follows, in the order it was found.
    """
    found = [t for t in targets_of(gaps) if t.source_kind == "craft"]
    if not order:
        return found
    rank = {name: i for i, name in enumerate(order)}
    return sorted(found, key=lambda t: rank.get(t.want, len(rank)))


def unsourced(gaps: Iterable[GapRow | PairRow]) -> list[Target]:
    """Rows whose source line did not classify.

    These are data problems, not results. A non-empty list is a bundle build
    failure, and the rows must never be rendered on a gear page: a reader
    checking what to run does not need to see the tooling's problems, and a row
    with no source is one nobody can act on.
    """
    return [t for t in targets_of(gaps) if t.source_kind == "unknown"]


# ---------------------------------------------------------------- item level


def tracks_for(ilvl: int, tracks: Mapping[str, Sequence[int]]) -> list[dict[str, Any]]:
    """Which upgrade tracks an item level can sit on, and the cap of each.

    Several item levels appear on two tracks. Only the in-game tooltip
    disambiguates, so every match is returned rather than one being picked.
    """
    return [
        {"track": name, "step": steps.index(ilvl) + 1, "cap": steps[-1]}
        for name, steps in tracks.items()
        if ilvl in steps
    ]


def coverage(spec_ref: SpecReference, item_stats: ItemStats | None) -> dict[str, Any]:
    """How much of a spec's Catalyst slots the reference data can verify.

    A tool that reports "unverifiable" has to know how often it does. A spec
    below full coverage is shipped as partially supported and says so, rather
    than quietly returning unverifiable rows.
    """
    items = item_stats.items if item_stats else {}
    needed = [
        e for e in spec_ref.mythic_bis
        if (key := slot_key(e.slot_label)) is not None and key in CATALYST_SLOTS
    ]
    # A row with no secondaries is as unverifiable as no row at all: identify()
    # returns "unknown" for an empty split exactly as it does for a missing
    # entry. Counting it as covered overstated what the engine can verify, and
    # this project's rule is that unverifiable never collapses into a pass.
    cached = [
        e for e in needed
        if (entry := items.get(str(e.wanted_id))) is not None and entry.get("secondaries")
    ]

    def missing(entry: BisEntry) -> dict[str, Any]:
        # Name the BASE, not the card title. On a Catalyst row the card is titled
        # with the tier item while the id is the base, so reporting the entry's
        # own name against that id produces lines naming one item beside another
        # item's id.
        cached_item = items.get(str(entry.wanted_id)) or {}
        return {
            "slot": entry.slot_label,
            "id": entry.wanted_id,
            "item": cached_item.get("name") or entry.name,
        }

    return {
        "catalyst_slots": len(needed),
        "cached": len(cached),
        "missing": [missing(e) for e in needed if e not in cached],
    }
