"""The gap engine.

Pure: no network, no configuration, no I/O, no database. Every function here
would give the same answer for any character on any realm, which is the test for
whether a rule belongs in it at all.

ADR 003 makes this a shared library and never a service. Putting a pure function
behind HTTP adds latency and a failure mode for nothing, and the guarantee that
the single-character and roster paths can never disagree about what a gap is
holds only because both call this same code -- which is now only true if both
depend on the same MAJOR version. See version.py.

What is deliberately absent: any ranking of one stat pair against another, any
score, any threshold, and anything that depends on whose character it is or what
they are saving charges for. Ranking secondaries needs a sim. Intent is input.

ON `__all__`. Everything named below is API this package promises not to break
within a major version, so it is curated rather than "whatever happens to be
importable". Three of these -- HeldItem, PairRow, Target -- are referenced by no
consumer today but appear in the RETURN TYPES of ones that are, so a caller
annotating `assess()` needs them; dropping them would export a function whose
type cannot be written down. `find_gaps` and `tracks_for` are exercised only by
tests today and are kept deliberately: both are entry points a service will want,
and the cost of promising a pure function is small.

Nothing with a leading underscore is exported. `_match_key` used to be imported
across this boundary by the bundle loader; `assert_sources_distinguishable`
replaces that -- see its docstring for why exposing the question beats exposing
the mechanism.
"""

from __future__ import annotations

from gear_gap_engine.gaps import (
    CATALYST_SLOTS,
    CLASS_SLUGS,
    MISSING,
    PAIRED,
    SECONDARY,
    BisEntry,
    EquippedItem,
    GapRow,
    HeldItem,
    IndistinguishableSources,
    ItemStats,
    PairRow,
    SourceRef,
    SpecReference,
    Target,
    assert_sources_distinguishable,
    assess,
    class_of,
    coverage,
    crafts,
    find_gaps,
    fingerprint,
    identify,
    make_source_parser,
    route,
    slot_key,
    targets_of,
    tracks_for,
    unsourced,
)
from gear_gap_engine.version import (
    IncompatibleBundle,
    __version__,
    assert_bundle_compatible,
)

__all__ = [
    # --- version and the bundle-compatibility contract -------------------
    "__version__",
    "IncompatibleBundle",
    "assert_bundle_compatible",
    # --- vocabulary: the words the rules are written in -------------------
    "CATALYST_SLOTS",
    "CLASS_SLUGS",
    "MISSING",
    "PAIRED",
    "SECONDARY",
    # --- data types, all of which appear in a public signature ------------
    "BisEntry",
    "EquippedItem",
    "GapRow",
    "HeldItem",
    "ItemStats",
    "PairRow",
    "SourceRef",
    "SpecReference",
    "Target",
    # --- the rules --------------------------------------------------------
    "assess",
    "class_of",
    "coverage",
    "crafts",
    "find_gaps",
    "fingerprint",
    "identify",
    "make_source_parser",
    "route",
    "slot_key",
    "targets_of",
    "tracks_for",
    "unsourced",
    # --- invariants the engine requires of its inputs ---------------------
    "IndistinguishableSources",
    "assert_sources_distinguishable",
]
