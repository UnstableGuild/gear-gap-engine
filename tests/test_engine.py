"""The gap rules. No network, no database, no live data.

Every case here is a rule the spec states or a mistake the project has already
made once. The prototype's test_gaps.py is the specification of correct
behaviour; these are those cases plus the ones slice 1's findings made relevant.
"""

from __future__ import annotations

import pytest

import gear_gap_engine
from gear_gap_engine import (
    CATALYST_SLOTS,
    SECONDARY,
    BisEntry,
    EquippedItem,
    ItemStats,
    SpecReference,
    assess,
    coverage,
    crafts,
    find_gaps,
    fingerprint,
    make_source_parser,
    route,
    targets_of,
    tracks_for,
    unsourced,
)

CHEST_ILVL = 311  # what a +10 end-of-run chest drops

# The guide's chest pick and its reference secondaries at 311. Inline rather than
# loaded: a rule that needs a data file to check is a rule nobody checks.
GUIDE_CHEST_ID = 239036
TIER_CHEST_ID = 271477

STATS = ItemStats(
    items={
        str(GUIDE_CHEST_ID): {
            "name": "Desert Guardian's Breastplate",
            "secondaries": {"CRIT_RATING": 72, "MASTERY_RATING": 111},
        },
        "273776": {
            "name": "Ancient General's Obsidian Pillars",
            "secondaries": {"CRIT_RATING": 80, "HASTE_RATING": 100},
        },
    }
)

BIS_CHEST = SpecReference(
    mythic_bis=[
        BisEntry("Chest", GUIDE_CHEST_ID, "Desert Guardian's Breastplate", "Temple of Sethraliss")
    ]
)
BIS_LEGS = SpecReference(
    mythic_bis=[
        BisEntry("Legs", 273776, "Ancient General's Obsidian Pillars", "Altar of Fangs")
    ]
)

parse_source = make_source_parser(
    ["Altar of Fangs", "Temple of Sethraliss", "Kings' Rest", "The Blinding Vale"],
    ["Venomous Abyss"],
)


def item(slot, name, ilvl, secondaries, *, tier=False, item_id=1):
    return EquippedItem(
        slot=slot, item_id=item_id, name=name, ilvl=ilvl,
        is_set_piece=tier, secondaries=secondaries,
    )


def gaps_for(equipped, spec_ref, stats=STATS, chest=CHEST_ILVL):
    return find_gaps(equipped, spec_ref, stats, chest, source_parser=parse_source)


def reasons(rows, slot):
    return next((list(r.reasons) for r in rows if r.slot == slot), None)


# --------------------------------------------------------------- the two rules


def test_a_wrong_base_at_the_ceiling_is_still_a_target():
    # The case that matters. A converted piece's secondaries are permanent, so a
    # slot sitting exactly at the chest item level can still be the wrong item.
    # An earlier version short-circuited on item level and dropped these.
    rows = gaps_for(
        {"chest": item("chest", "Baleful Grave-Knight's Breastplate", 311,
                       {"HASTE_RATING": 68, "VERSATILITY": 114},
                       tier=True, item_id=TIER_CHEST_ID)},
        BIS_CHEST,
    )
    assert reasons(rows, "chest") == ["wrong_base"]


def test_the_right_base_at_the_ceiling_is_not_a_target():
    rows = gaps_for(
        {"chest": item("chest", "Baleful Grave-Knight's Breastplate", 311,
                       {"CRIT_RATING": 72, "MASTERY_RATING": 111},
                       tier=True, item_id=TIER_CHEST_ID)},
        BIS_CHEST,
    )
    assert reasons(rows, "chest") is None


def test_a_slot_above_what_the_dungeon_drops_is_never_a_target():
    # Myth 334 legs against a 311 dungeon drop. Re-converting would cost 23 item
    # levels, so this must not appear however the secondaries compare.
    rows = gaps_for(
        {"legs": item("legs", "Baleful Grave-Knight's Greaves", 334,
                      {"CRIT_RATING": 59, "MASTERY_RATING": 142},
                      tier=True, item_id=271473)},
        BIS_LEGS,
    )
    assert reasons(rows, "legs") is None


def test_below_the_ceiling_is_a_target_on_item_level_alone():
    rows = gaps_for(
        {"chest": item("chest", "Baleful Grave-Knight's Breastplate", 298,
                       {"CRIT_RATING": 72, "MASTERY_RATING": 111},
                       tier=True, item_id=TIER_CHEST_ID)},
        BIS_CHEST,
    )
    assert reasons(rows, "chest") == ["below_chest_ilvl"]


def test_item_level_and_identity_stack_as_separate_reasons():
    rows = gaps_for(
        {"chest": item("chest", "Something Else", 298,
                       {"HASTE_RATING": 68, "VERSATILITY": 114},
                       tier=True, item_id=TIER_CHEST_ID)},
        BIS_CHEST,
    )
    assert reasons(rows, "chest") == ["below_chest_ilvl", "wrong_base"]


def test_a_non_tier_slot_is_identified_by_item_id_with_no_stats_needed():
    rows = find_gaps(
        {"chest": item("chest", "Desert Guardian's Breastplate", 311,
                       {"CRIT_RATING": 72, "MASTERY_RATING": 111}, item_id=GUIDE_CHEST_ID)},
        BIS_CHEST, None, CHEST_ILVL, source_parser=parse_source,
    )
    assert reasons(rows, "chest") is None


def test_an_empty_slot_is_a_gap():
    rows = gaps_for({}, BIS_CHEST)
    assert reasons(rows, "chest") == ["empty"]


# ------------------------------------------------------------ unverifiable


def test_an_uncached_reference_item_reports_unverifiable_not_a_false_pass():
    # unverifiable is a real answer. It means the reference data does not cover
    # the item, not that the slot is fine, and it must never collapse into a pass.
    spec = SpecReference(
        mythic_bis=[BisEntry("Chest", 111111, "Uncached Chest", "Temple of Sethraliss")]
    )
    rows = gaps_for(
        {"chest": item("chest", "Some Tier Chest", 311,
                       {"CRIT_RATING": 72, "MASTERY_RATING": 111}, tier=True, item_id=999)},
        spec,
    )
    assert reasons(rows, "chest") == ["unverifiable"]


def test_an_item_with_no_secondaries_is_unverifiable_not_a_pass():
    # 14 of the 82 cached items carry an effect instead of a stat line. A blank
    # split reads as unknown, never as a match.
    stats = ItemStats(items={"555": {"name": "Effect Trinket", "secondaries": {}}})
    spec = SpecReference(mythic_bis=[BisEntry("Chest", 555, "Effect Chest", "Kings' Rest")])
    rows = gaps_for(
        {"chest": item("chest", "Tier Chest", 311, {"CRIT_RATING": 10}, tier=True, item_id=9)},
        spec, stats,
    )
    assert reasons(rows, "chest") == ["unverifiable"]


# ------------------------------------------------------------- the fingerprint


def test_the_fingerprint_is_item_level_invariant():
    # The same base carried to 334 by crests still reads as the right item.
    rows = gaps_for(
        {"chest": item("chest", "Baleful Grave-Knight's Breastplate", 334,
                       {"CRIT_RATING": 77, "MASTERY_RATING": 119},
                       tier=True, item_id=TIER_CHEST_ID)},
        BIS_CHEST,
    )
    assert reasons(rows, "chest") is None


def test_the_fingerprint_is_scale_invariant():
    # Slice 1 found the API reports much smaller secondary magnitudes than a
    # tooltip does. Each side is normalised against its own total, so only the
    # ratio is ever compared. This test fails the moment anyone compares raw
    # magnitudes instead.
    tooltip = {"CRIT_RATING": 720, "MASTERY_RATING": 1110}
    api = {"CRIT_RATING": 72, "MASTERY_RATING": 111}
    assert fingerprint(tooltip) == fingerprint(api)

    stats = ItemStats(items={str(GUIDE_CHEST_ID): {"name": "x", "secondaries": tooltip}})
    rows = gaps_for(
        {"chest": item("chest", "Tier Chest", 311, api, tier=True, item_id=TIER_CHEST_ID)},
        BIS_CHEST, stats,
    )
    assert reasons(rows, "chest") is None


def test_an_empty_or_zero_split_has_no_fingerprint():
    assert fingerprint({}) is None
    assert fingerprint(None) is None
    assert fingerprint({"CRIT_RATING": 0}) is None


def test_the_engine_and_the_bundle_share_one_secondary_vocabulary():
    # The equipped side comes from the Blizzard API and the reference side from
    # item_stats.json. They agree on these four names today, so no translation
    # layer exists. If either ever moves to numeric rating ids, this fails and
    # the translation belongs at the boundary that changed.
    assert SECONDARY == {"CRIT_RATING", "HASTE_RATING", "MASTERY_RATING", "VERSATILITY"}
    assert CATALYST_SLOTS == {"head", "shoulder", "chest", "hands", "legs"}


# ------------------------------------------------------------------ sources


def test_a_craft_is_a_gap_but_never_a_route_entry():
    spec = SpecReference(
        mythic_bis=[BisEntry("Bracers", 237834, "Spellbreaker's Bracers",
                             "Crafted by Blacksmithing")]
    )
    rows = gaps_for({"wrist": item("wrist", "Some Bracers", 305, {"CRIT_RATING": 50})}, spec)
    assert [r.source_kind for r in rows] == ["craft"]
    assert [r.source for r in rows] == ["Blacksmithing"]
    assert route(rows) == {}
    assert [r.want for r in crafts(rows)] == ["Spellbreaker's Bracers"]


def test_a_raid_source_is_reported_but_not_routed():
    # The gap list is which slots are wrong regardless of where the fix comes
    # from. Hiding raid rows would show a slot as fine when its answer is a raid
    # drop. Routing them would suggest queueing a weekly lockout.
    spec = SpecReference(
        mythic_bis=[BisEntry("Waist", 268259, "Girdle of Toxic Regret",
                             "Coiled Altar in Venomous Abyss")]
    )
    rows = gaps_for({"waist": item("waist", "Some Belt", 305, {"CRIT_RATING": 50})}, spec)
    assert [r.source_kind for r in rows] == ["raid"]
    assert route(rows) == {}


def test_the_guides_crafting_order_wins_over_discovery_order():
    spec = SpecReference(
        mythic_bis=[
            BisEntry("Bracers", 1, "Spellbreaker's Bracers", "Crafted by Blacksmithing"),
            BisEntry("Ring", 2, "Masterwork Sin'dorei Band", "Crafted by Jewelcrafting"),
        ]
    )
    rows = gaps_for(
        {
            "wrist": item("wrist", "Some Bracers", 305, {"CRIT_RATING": 50}),
            "finger1": item("finger1", "Ring A", 305, {"CRIT_RATING": 50}),
            "finger2": item("finger2", "Ring B", 305, {"CRIT_RATING": 50}),
        },
        spec,
    )
    order = ["Masterwork Sin'dorei Band", "Spellbreaker's Bracers"]
    assert [r.want for r in crafts(rows, order)] == order


def test_an_unclassifiable_source_is_surfaced_not_swallowed():
    spec = SpecReference(mythic_bis=[BisEntry("Off Hand", 9, "Phantom Item", "")])
    rows = gaps_for(
        {
            "trinket1": item("trinket1", "T", 305, {"CRIT_RATING": 50}),
            "trinket2": item("trinket2", "T", 305, {"CRIT_RATING": 50}),
        },
        spec,
    )
    assert [r.source_kind for r in unsourced(rows)] == ["unknown"]


def test_a_profession_wins_over_a_location_in_the_same_line():
    parse = make_source_parser(["Kings' Rest"], [])
    assert parse("Crafted by Blacksmithing, drops in Kings' Rest").kind == "craft"


def test_dungeon_matching_survives_apostrophes_and_articles():
    # The season pool records "Kings' Rest" and the guide writes "King's Rest".
    # They are one dungeon. The pool's spelling is what comes back, because the
    # route and the matrix group by it.
    parse = make_source_parser(["Kings' Rest", "The Blinding Vale"], [])
    assert parse("King's Rest").name == "Kings' Rest"
    assert parse("King's Rest with Catalyst").name == "Kings' Rest"
    assert parse("Blinding Vale").name == "The Blinding Vale"
    assert parse("The Blinding Vale").name == "The Blinding Vale"


def test_the_catalyst_flag_reads_the_source_text():
    parse = make_source_parser(["Kings' Rest"], [])
    assert parse("Catalyst from King's Rest").catalyst
    assert parse("King's Rest with Catalyst").catalyst
    assert not parse("King's Rest").catalyst


def test_a_raid_classifies_before_a_dungeon():
    parse = make_source_parser(["Kings' Rest"], ["Venomous Abyss"])
    assert parse("Ula'tek in Venomous Abyss").kind == "raid"


# --------------------------------------------------------------- paired slots


# ADR 006: a paired slot is compared as a set, never entry by entry.

TWO_RINGS = SpecReference(
    mythic_bis=[
        BisEntry("Ring", 158366, "Charged Sandstone Band", "Kings' Rest"),
        BisEntry("Ring", 159459, "Ritual Binder's Ring", "Kings' Rest"),
    ]
)


def rings(a_id, a_ilvl, b_id, b_ilvl):
    return {
        "finger1": item("finger1", f"Ring {a_id}", a_ilvl, {"CRIT_RATING": 50}, item_id=a_id),
        "finger2": item("finger2", f"Ring {b_id}", b_ilvl, {"CRIT_RATING": 50}, item_id=b_id),
    }


def test_a_paired_slot_is_one_row_not_one_per_entry():
    # Two guide entries, one finding. Entry-by-entry double-counts by
    # construction, which is what the set framing exists to remove.
    rows = assess(rings(1, 311, 2, 311), TWO_RINGS, STATS, CHEST_ILVL, parse_source)
    assert len(rows) == 1
    assert rows[0].bis_slot == "Ring"
    assert rows[0].named == 2


def test_holding_neither_names_both_as_missing():
    rows = assess(rings(1, 311, 2, 311), TWO_RINGS, STATS, CHEST_ILVL, parse_source)
    assert rows[0].matched == ()
    assert [t.want for t in rows[0].missing] == [
        "Charged Sandstone Band", "Ritual Binder's Ring"
    ]
    assert rows[0].is_gap


def test_holding_one_credits_it_and_names_only_the_other():
    # The ADR's worked example: you hold 1 of the 2 rings the guide names; the
    # missing one is Ritual Binder's Ring.
    rows = assess(rings(158366, 311, 2, 298), TWO_RINGS, STATS, CHEST_ILVL, parse_source)
    assert rows[0].matched == ("Charged Sandstone Band",)
    assert [t.want for t in rows[0].missing] == ["Ritual Binder's Ring"]


def test_holding_both_is_not_a_gap():
    rows = assess(rings(158366, 311, 159459, 311), TWO_RINGS, STATS, CHEST_ILVL, parse_source)
    assert rows[0].matched == ("Charged Sandstone Band", "Ritual Binder's Ring")
    assert rows[0].missing == ()
    assert not rows[0].is_gap
    assert route(find_gaps(rings(158366, 311, 159459, 311), TWO_RINGS,
                           STATS, CHEST_ILVL, parse_source)) == {}


def test_one_equipped_item_cannot_satisfy_two_guide_entries():
    # A single ring credits exactly one entry, so wearing one named ring can
    # never make the pair look complete.
    spec = SpecReference(
        mythic_bis=[
            BisEntry("Ring", 158366, "Charged Sandstone Band", "Kings' Rest"),
            BisEntry("Ring", 158366, "Charged Sandstone Band", "Kings' Rest"),
        ]
    )
    rows = assess(rings(158366, 311, 99, 311), spec, STATS, CHEST_ILVL, parse_source)
    assert len(rows[0].matched) == 1
    assert len(rows[0].missing) == 1


def test_a_pair_above_the_ceiling_is_not_a_target():
    # Nothing worn in the pair is replaceable by what a key drops, so the missing
    # rings are still named but there is nothing to queue.
    rows = assess(rings(1, 321, 2, 331), TWO_RINGS, STATS, CHEST_ILVL, parse_source)
    assert rows[0].improvable is False
    assert len(rows[0].missing) == 2
    assert not rows[0].is_gap
    assert rows[0].targets == ()


def test_a_pair_with_one_replaceable_slot_is_a_target():
    rows = assess(rings(1, 311, 2, 331), TWO_RINGS, STATS, CHEST_ILVL, parse_source)
    assert rows[0].improvable is True
    assert rows[0].is_gap


def test_an_empty_pair_is_always_improvable():
    rows = assess({}, TWO_RINGS, STATS, CHEST_ILVL, parse_source)
    assert rows[0].held == ()
    assert rows[0].improvable is True
    assert len(rows[0].missing) == 2


def test_a_pair_row_never_claims_one_of_the_two_slots():
    rows = assess(rings(1, 311, 2, 311), TWO_RINGS, STATS, CHEST_ILVL, parse_source)
    assert rows[0].as_dict()["slot"] is None
    assert rows[0].as_dict()["slots"] == ["finger1", "finger2"]
    assert rows[0].bis_slot == "Ring"


def test_a_pair_reports_what_is_worn_in_both_slots():
    rows = assess(rings(1, 311, 2, 298), TWO_RINGS, STATS, CHEST_ILVL, parse_source)
    assert [(h.slot, h.ilvl) for h in rows[0].held] == [("finger1", 311), ("finger2", 298)]


def test_a_pair_keeps_the_position_the_guide_first_named_it():
    spec = SpecReference(
        mythic_bis=[
            BisEntry("Chest", GUIDE_CHEST_ID, "Desert Guardian's Breastplate",
                     "Temple of Sethraliss"),
            BisEntry("Ring", 158366, "Charged Sandstone Band", "Kings' Rest"),
            BisEntry("Legs", 273776, "Ancient General's Obsidian Pillars", "Altar of Fangs"),
            BisEntry("Ring", 159459, "Ritual Binder's Ring", "Kings' Rest"),
        ]
    )
    rows = assess(rings(1, 311, 2, 311), spec, STATS, CHEST_ILVL, parse_source)
    assert [r.bis_slot for r in rows] == ["Chest", "Ring", "Legs"]


def test_each_missing_item_of_a_pair_routes_to_its_own_dungeon():
    spec = SpecReference(
        mythic_bis=[
            BisEntry("Ring", 158366, "Charged Sandstone Band", "Temple of Sethraliss"),
            BisEntry("Ring", 159459, "Ritual Binder's Ring", "Altar of Fangs"),
        ]
    )
    routed = route(find_gaps(rings(1, 311, 2, 311), spec, STATS, CHEST_ILVL, parse_source))
    assert set(routed) == {"Temple of Sethraliss", "Altar of Fangs"}
    assert all(len(v) == 1 for v in routed.values())


def test_trinkets_are_paired_the_same_way():
    spec = SpecReference(
        mythic_bis=[
            BisEntry("Trinket", 100, "Trinket A", "Kings' Rest"),
            BisEntry("Trinket", 200, "Trinket B", "Altar of Fangs"),
        ]
    )
    equipped = {
        "trinket1": item("trinket1", "Junk", 308, {"CRIT_RATING": 1}, item_id=999),
        "trinket2": item("trinket2", "Trinket B", 311, {"CRIT_RATING": 1}, item_id=200),
    }
    rows = assess(equipped, spec, STATS, CHEST_ILVL, parse_source)
    assert rows[0].matched == ("Trinket B",)
    assert [t.want for t in rows[0].missing] == ["Trinket A"]


def test_an_unrecognised_slot_label_is_dropped_not_guessed():
    spec = SpecReference(mythic_bis=[BisEntry("Tabard", 1, "A Tabard", "Kings' Rest")])
    assert assess({}, spec, STATS, CHEST_ILVL, parse_source) == []


# ------------------------------------------------------------------ trinkets


def test_a_trinket_outside_the_s_and_a_tiers_is_not_a_target():
    spec = SpecReference(
        mythic_bis=[BisEntry("Trinket", 1, "B Tier Trinket", "Kings' Rest")],
        trinket_tiers={"B": {"Mythic+": ["B Tier Trinket"]}},
    )
    assert gaps_for({}, spec) == []


def test_an_s_tier_trinket_is_a_target():
    spec = SpecReference(
        mythic_bis=[BisEntry("Trinket", 1, "S Tier Trinket", "Kings' Rest")],
        trinket_tiers={"S": {"Mythic+": ["S Tier Trinket"]}},
    )
    assert len(gaps_for({}, spec)) == 1


def test_an_untiered_trinket_is_still_a_target():
    spec = SpecReference(mythic_bis=[BisEntry("Trinket", 1, "Untiered", "Kings' Rest")])
    assert len(gaps_for({}, spec)) == 1


# ----------------------------------------------------- assess vs find_gaps


def test_assess_reports_satisfied_slots_and_find_gaps_filters_them():
    # Two views over one dataset. A view that lists only problems cannot be read
    # as a picture of a character, and the satisfied slots are what make it one.
    equipped = {
        "chest": item("chest", "Desert Guardian's Breastplate", 311,
                      {"CRIT_RATING": 72, "MASTERY_RATING": 111}, item_id=GUIDE_CHEST_ID),
        "legs": item("legs", "Wrong Legs", 298, {"CRIT_RATING": 80}, item_id=42),
    }
    spec = SpecReference(mythic_bis=list(BIS_CHEST.mythic_bis) + list(BIS_LEGS.mythic_bis))
    all_rows = assess(equipped, spec, STATS, CHEST_ILVL, parse_source)
    gap_rows = find_gaps(equipped, spec, STATS, CHEST_ILVL, parse_source)
    assert len(all_rows) == 2
    assert [r.reasons for r in all_rows] == [(), ("below_chest_ilvl", "wrong_item")]
    assert len(gap_rows) == 1
    assert gap_rows[0].slot == "legs"


# -------------------------------------------------------- the catalyst row


def test_a_catalyst_row_names_what_to_farm_and_what_it_becomes():
    # "farm Warhelm of the Consecrated Flame" is an instruction nobody can
    # follow, because it does not drop anywhere.
    stats = ItemStats(items={"239050": {"name": "Helm of the Raptor King",
                                        "secondaries": {"CRIT_RATING": 100}}})
    spec = SpecReference(
        mythic_bis=[BisEntry("Helm", 271474, "Baleful Grave-Knight's Casque",
                             "Catalyst from Kings' Rest", catalyst_input=239050)]
    )
    rows = gaps_for({}, spec, stats)
    assert rows[0].want_id == 239050
    assert rows[0].farm == "Helm of the Raptor King"
    assert rows[0].becomes == "Baleful Grave-Knight's Casque"
    assert rows[0].catalyst is True


def test_a_plain_row_has_no_becomes():
    rows = gaps_for({}, BIS_CHEST)
    assert rows[0].farm == "Desert Guardian's Breastplate"
    assert rows[0].becomes is None


# ------------------------------------------------------------------- route


def test_the_route_ranks_dungeons_by_how_many_slots_they_close():
    spec = SpecReference(
        mythic_bis=[
            BisEntry("Chest", 1, "A", "Temple of Sethraliss"),
            BisEntry("Legs", 2, "B", "Temple of Sethraliss"),
            BisEntry("Feet", 3, "C", "Altar of Fangs"),
        ]
    )
    assert list(route(gaps_for({}, spec))) == ["Temple of Sethraliss", "Altar of Fangs"]


def test_an_empty_route_beside_gaps_is_a_real_state():
    # Nothing left in keys for this character: everything remaining is a craft or
    # a raid. Not an error.
    spec = SpecReference(
        mythic_bis=[BisEntry("Bracers", 1, "B", "Crafted by Blacksmithing")]
    )
    rows = gaps_for({}, spec)
    assert rows and route(rows) == {}


# ---------------------------------------------------------------- coverage


def test_coverage_counts_only_catalyst_slots():
    spec = SpecReference(
        mythic_bis=[
            BisEntry("Chest", GUIDE_CHEST_ID, "Cached", "Kings' Rest"),
            BisEntry("Legs", 999999, "Uncached", "Kings' Rest"),
            BisEntry("Neck", 888888, "Not a catalyst slot", "Kings' Rest"),
        ]
    )
    result = coverage(spec, STATS)
    assert result["catalyst_slots"] == 2
    assert result["cached"] == 1
    assert [m["id"] for m in result["missing"]] == [999999]


def test_coverage_names_the_base_not_the_card_title():
    # On a Catalyst row the card is titled with the tier item while the id is the
    # base. Reporting the entry's own name against that id names one item beside
    # another item's id.
    spec = SpecReference(
        mythic_bis=[BisEntry("Chest", 271477, "Baleful Grave-Knight's Breastplate",
                             "Kings' Rest", catalyst_input=GUIDE_CHEST_ID)]
    )
    stats = ItemStats(items={})
    assert coverage(spec, stats)["missing"][0]["item"] == "Baleful Grave-Knight's Breastplate"
    assert coverage(spec, STATS)["cached"] == 1


# ------------------------------------------------------------------ tracks


def test_an_ambiguous_item_level_returns_every_track_it_could_be_on():
    tracks = {"Hero": [305, 308, 311, 315, 318, 321], "Myth": [318, 321, 324, 328, 331, 334]}
    assert [t["track"] for t in tracks_for(321, tracks)] == ["Hero", "Myth"]
    assert [t["track"] for t in tracks_for(334, tracks)] == ["Myth"]
    assert tracks_for(1, tracks) == []


# ------------------------------------------------------------------ purity


def test_the_engine_imports_only_the_standard_library():
    """ADR 003: the engine is a library and stays one.

    Stricter than the version that shipped inside the service, which could only
    check that it imported no `gear_gap.*` service module. Standing alone, the
    real guarantee is available: every import is stdlib or this package. That is
    what lets every service depend on it without inheriting a dependency, and
    what makes "would give the same answer for any character" checkable rather
    than asserted.
    """
    import ast
    import pathlib
    import sys

    for source in pathlib.Path(gear_gap_engine.__file__).parent.glob("*.py"):
        tree = ast.parse(source.read_text())
        imported = {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        } | {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        outside = {
            m for m in imported
            if m and m != "gear_gap_engine" and m not in sys.stdlib_module_names
        }
        assert not outside, f"{source.name} imports outside the stdlib: {outside}"


def test_the_engine_does_not_need_optional_arguments():
    # No config, no stats, no chest level: it still answers, and the answer is
    # honest about what it could not check.
    with pytest.raises(TypeError):
        find_gaps()  # type: ignore[call-arg]
    rows = find_gaps({}, BIS_CHEST)
    assert [r.reasons for r in rows] == [("empty",)]


def test_a_worn_guide_ring_is_not_reported_as_a_gap():
    """Was a strict xfail until ADR 006. The reference engine compared both
    paired entries against the weaker of the two equipped items, so a guide ring
    worn in the stronger slot was still reported as a gap and the page told the
    reader to farm an item they had on."""
    spec = SpecReference(
        mythic_bis=[
            BisEntry("Ring", 158366, "Charged Sandstone Band", "Kings' Rest"),
            BisEntry("Ring", 159459, "Ritual Binder's Ring", "Kings' Rest"),
        ]
    )
    rows = gaps_for(
        {
            "finger1": item("finger1", "Charged Sandstone Band", 311,
                            {"CRIT_RATING": 202, "MASTERY_RATING": 151}, item_id=158366),
            "finger2": item("finger2", "Junk Ring", 298, {"CRIT_RATING": 50}, item_id=99999),
        },
        spec,
    )
    # Same intent, expressed against targets now that a pair is one row: nothing
    # the page tells you to go and get may be an item you are wearing.
    farmed = [t.want_id for t in targets_of(rows)]
    assert 158366 not in farmed, "the character is wearing this ring; it is not a gap"
    assert farmed == [159459], "the other named ring is still missing and still a target"


# --------------------------------------------------- ADR 005: identity always


def test_identity_is_tested_above_the_ceiling_too():
    # It costs one pure comparison and buys the page the difference between
    # "holds the guide's pick" and "holds something else nobody can farm".
    rows = assess(
        {"legs": item("legs", "Baleful Grave-Knight's Greaves", 334,
                      {"CRIT_RATING": 59, "MASTERY_RATING": 142},
                      tier=True, item_id=271473)},
        BIS_LEGS, STATS, CHEST_ILVL, parse_source,
    )
    assert rows[0].reachable is False
    assert rows[0].identity == "no"
    assert rows[0].reasons == ()


def test_a_slot_above_the_ceiling_holding_the_guides_pick_reports_yes():
    rows = assess(
        {"legs": item("legs", "Ancient General's Obsidian Pillars", 334,
                      {"CRIT_RATING": 80, "HASTE_RATING": 100}, item_id=273776)},
        BIS_LEGS, STATS, CHEST_ILVL, parse_source,
    )
    assert (rows[0].identity, rows[0].reachable, rows[0].reasons) == ("yes", False, ())


def test_an_unreachable_verdict_never_becomes_a_reason():
    # THE REGRESSION GUARD. Reachability still decides whether a slot is a
    # target, so testing identity everywhere cannot change the gap list or the
    # route. Only what the page can say changes.
    equipped = {"legs": item("legs", "Something Else", 334,
                             {"CRIT_RATING": 1, "HASTE_RATING": 99}, item_id=1)}
    gaps = find_gaps(equipped, BIS_LEGS, STATS, CHEST_ILVL, parse_source)
    assert gaps == []
    assert route(gaps) == {}
    # And route() will not be talked into it by the full assessment either.
    assert route(assess(equipped, BIS_LEGS, STATS, CHEST_ILVL, parse_source)) == {}


def test_a_reachable_slot_still_turns_its_verdict_into_a_reason():
    equipped = {"legs": item("legs", "Something Else", 305,
                             {"CRIT_RATING": 1, "HASTE_RATING": 99}, item_id=1)}
    rows = find_gaps(equipped, BIS_LEGS, STATS, CHEST_ILVL, parse_source)
    assert rows[0].identity == "no"
    assert rows[0].reachable is True
    assert list(rows[0].reasons) == ["below_chest_ilvl", "wrong_item"]


def test_an_empty_slot_reports_no_identity_and_is_reachable():
    rows = assess({}, BIS_LEGS, STATS, CHEST_ILVL, parse_source)
    assert (rows[0].identity, rows[0].reachable, rows[0].reasons) == ("no", True, ("empty",))


# ------------------------------------------ two more source kinds, never routed


def test_a_bare_catalyst_is_its_own_kind():
    # 17 M+ picks across the published specs say only "Catalyst": a conversion
    # whose base the guide does not locate. Real, and not farmable.
    parse = make_source_parser(["Kings' Rest"], ["The Venomous Abyss"])
    found = parse("Catalyst")
    assert (found.kind, found.name, found.catalyst) == ("catalyst", "Catalyst", True)


def test_a_catalyst_that_names_a_place_is_still_that_place():
    # "Catalyst from King's Rest" is a dungeon row that happens to need
    # converting. Only a Catalyst naming nowhere is a catalyst source.
    parse = make_source_parser(["Kings' Rest"], [])
    found = parse("Catalyst from King's Rest")
    assert (found.kind, found.name, found.catalyst) == ("dungeon", "Kings' Rest", True)


def test_the_great_vault_is_its_own_kind():
    parse = make_source_parser(["Kings' Rest"], [])
    found = parse("The Great Vault")
    assert (found.kind, found.name) == ("vault", "The Great Vault")


def test_neither_new_kind_is_ever_routed():
    # Hiding a gap makes the tool lie about the slot; routing something
    # unfarmable makes it useless. Both are listed and neither is queued.
    spec = SpecReference(
        mythic_bis=[
            BisEntry("Helm", 1, "Convert Me", "Catalyst"),
            BisEntry("Chest", 2, "Vault Me", "The Great Vault"),
            BisEntry("Legs", 3, "Farm Me", "Altar of Fangs"),
        ]
    )
    rows = gaps_for({}, spec)
    assert len(rows) == 3, "all three are still gaps"
    assert list(route(rows)) == ["Altar of Fangs"]


def test_an_unrecognised_source_is_still_unknown():
    # "Nexus King Salhadaar" is in no season list. Unknown, and the build says so
    # rather than guessing at it.
    parse = make_source_parser(["Kings' Rest"], ["The Venomous Abyss"])
    assert parse("Nexus King Salhadaar").kind == "unknown"


# ------------------------------------------------ matching a boss by short name


def test_a_boss_named_without_its_epithet_still_classifies():
    # The guide writes "Vashnik" where the season pool has "Vashnik the
    # Malignant". Testing only "pool inside source" misses every one of those.
    parse = make_source_parser([], ["Vashnik the Malignant", "The Coiled Altar"])
    assert parse("Vashnik").name == "Vashnik the Malignant"
    assert parse("Coiled Altar").name == "The Coiled Altar"


def test_the_pools_spelling_is_what_comes_back():
    parse = make_source_parser([], ["The Lost Explorers"])
    assert parse("Lost Explorers").name == "The Lost Explorers"


def test_a_short_fragment_does_not_match_by_containment():
    # The two-way test is guarded: a fragment must not find a pool name it
    # happens to sit inside.
    parse = make_source_parser(["Kings' Rest"], [])
    assert parse("Rest").kind == "unknown"


def test_a_longer_source_still_matches_the_pool_name_inside_it():
    parse = make_source_parser(["Altar of Fangs"], [])
    assert parse("Some Boss in Altar of Fangs").name == "Altar of Fangs"


# --------------------------------------------------- coverage counts truthfully


def test_a_cached_item_with_no_secondaries_does_not_count_as_covered():
    # identify() returns "unknown" for an empty split exactly as it does for a
    # missing row, so counting it as covered overstated what can be verified.
    # unverifiable never collapses into a pass.
    spec = SpecReference(mythic_bis=[BisEntry("Chest", 555, "Effect Chest", "Kings' Rest")])
    stats = ItemStats(items={"555": {"name": "Effect Chest", "secondaries": {}}})
    result = coverage(spec, stats)
    assert result == {"catalyst_slots": 1, "cached": 0,
                      "missing": [{"slot": "Chest", "id": 555, "item": "Effect Chest"}]}


def test_a_cached_item_with_secondaries_counts_as_covered():
    spec = SpecReference(mythic_bis=[BisEntry("Chest", GUIDE_CHEST_ID, "Cached", "Kings' Rest")])
    assert coverage(spec, STATS)["cached"] == 1


def test_coverage_names_which_slots_are_missing():
    spec = SpecReference(
        mythic_bis=[
            BisEntry("Chest", GUIDE_CHEST_ID, "Cached", "Kings' Rest"),
            BisEntry("Legs", 999999, "Uncached", "Kings' Rest"),
        ]
    )
    result = coverage(spec, STATS)
    assert (result["catalyst_slots"], result["cached"]) == (2, 1)
    assert [m["id"] for m in result["missing"]] == [999999]


# ------------------------------- a craft is not gated on what a key can drop

CRAFT_PARSE = make_source_parser(dungeons=["King's Rest"], raids=[])

PAIR_WITH_A_CRAFT = SpecReference(mythic_bis=[
    BisEntry(slot_label="Ring", item_id=1, name="Charged Sandstone Band",
             source="King's Rest"),
    BisEntry(slot_label="Ring", item_id=2, name="Masterwork Sin'dorei Band",
             source="Crafted by Jewelcrafting"),
])

SINGLE_CRAFT = SpecReference(mythic_bis=[
    BisEntry(slot_label="Bracers", item_id=7, name="Spellbreaker's Bracers",
             source="Crafted by Blacksmithing"),
])


def _rings(ilvl):
    return {
        "finger1": EquippedItem(slot="finger1", item_id=90, name="A", ilvl=ilvl),
        "finger2": EquippedItem(slot="finger2", item_id=91, name="B", ilvl=ilvl),
    }


def test_a_crafted_want_survives_a_slot_a_key_cannot_improve():
    """Reachability asks whether a key's chest could beat what is worn. A
    crafted item does not come out of a key -- it is obtainable at any item
    level, at any time -- so gating it on that hid a real, actionable gap
    behind a rule about dungeons. Someone wearing 340 rings still does not own
    the ring the guide names.
    """
    gaps = find_gaps(_rings(340), PAIR_WITH_A_CRAFT, None, 311, CRAFT_PARSE)
    assert [c.want for c in crafts(gaps)] == ["Masterwork Sin'dorei Band"]


def test_but_the_pairs_dungeon_want_is_still_not_routed():
    """The other half, and the reason the first fix was wrong. Lifting the gate
    for the whole pair let its DUNGEON want back into the route, which is the
    rule that keeps a 311 drop off a 334 slot. The gate is per target."""
    gaps = find_gaps(_rings(340), PAIR_WITH_A_CRAFT, None, 311, CRAFT_PARSE)
    assert route(gaps) == {}


def test_below_the_ceiling_both_halves_still_behave():
    gaps = find_gaps(_rings(300), PAIR_WITH_A_CRAFT, None, 311, CRAFT_PARSE)
    assert [c.want for c in crafts(gaps)] == ["Masterwork Sin'dorei Band"]
    assert list(route(gaps)) == ["King's Rest"]


def test_a_single_crafted_slot_survives_the_ceiling_too():
    """Two of the four roster specs have bracers with no dungeon answer at all.
    A slot whose only answer is a craft, silently showing nothing, is the worst
    version of this -- the reader concludes the slot is fine."""
    worn = {"wrist": EquippedItem(slot="wrist", item_id=99, name="Old", ilvl=340)}
    gaps = find_gaps(worn, SINGLE_CRAFT, None, 311, CRAFT_PARSE)
    assert [c.want for c in crafts(gaps)] == ["Spellbreaker's Bracers"]
    assert route(gaps) == {}


def test_a_pair_is_a_gap_exactly_when_it_has_actionable_targets():
    """is_gap and targets drifting apart is what hid this: find_gaps filters on
    is_gap, so a pair that was not a gap never reached crafts() however
    carefully targets was written."""
    rows = assess(_rings(340), PAIR_WITH_A_CRAFT, None, 311, CRAFT_PARSE)
    pair = next(r for r in rows if getattr(r, "bis_slot", None) == "Ring")
    assert pair.improvable is False
    assert pair.is_gap is True
    assert [t.want for t in pair.targets] == ["Masterwork Sin'dorei Band"]
