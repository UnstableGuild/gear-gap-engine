"""The two things this package promises beyond the rules themselves."""

from __future__ import annotations

import pytest

import gear_gap_engine
from gear_gap_engine import (
    IncompatibleBundle,
    IndistinguishableSources,
    assert_bundle_compatible,
    assert_sources_distinguishable,
)

# ------------------------------------------------ the source-name invariant


def test_a_distinguishable_pool_passes():
    # Returns None and does not raise; the point is that it does not raise.
    assert_sources_distinguishable(
        ["Kings' Rest", "Ruby Life Pools", "The Blinding Vale", "Murder Row"]
    )


def test_a_name_contained_in_another_is_refused():
    """The matcher squashes to letters and digits, which is only safe while no
    name is a substring of another once squashed. Refused at load rather than
    silently classifying one dungeon's rows as the other's."""
    with pytest.raises(IndistinguishableSources) as caught:
        assert_sources_distinguishable(["Murder Row", "Murder Row Annex"])
    assert "Murder Row" in str(caught.value)


def test_orthography_is_not_identity():
    """The season pool records "Kings' Rest" and the guide writes "King's
    Rest". Those are one dungeon, so they collide -- which is the check
    working, not failing."""
    with pytest.raises(IndistinguishableSources):
        assert_sources_distinguishable(["Kings' Rest", "King's Rest"])


def test_the_leading_article_is_ignored():
    with pytest.raises(IndistinguishableSources):
        assert_sources_distinguishable(["The Blinding Vale", "Blinding Vale"])


def test_the_private_normaliser_is_not_exported():
    """`_match_key` was imported across this boundary by the bundle loader.
    Exposing the question instead of the mechanism is what lets the
    normalisation change without breaking a consumer."""
    assert "_match_key" not in gear_gap_engine.__all__
    assert not hasattr(gear_gap_engine, "_match_key")


# ------------------------------------------------- the bundle version contract


def test_the_same_major_is_readable():
    assert_bundle_compatible(gear_gap_engine.__version__)


def test_a_different_major_is_refused():
    """slot_key and fingerprint decide how items are KEYED INTO a bundle and the
    matcher reads those keys back. Skew writes under one scheme and reads under
    another: every lookup misses and nothing looks unhealthy."""
    with pytest.raises(IncompatibleBundle) as caught:
        assert_bundle_compatible("2.0.0")
    assert "rebuilt" in str(caught.value)


def test_minor_and_patch_drift_within_a_major_is_fine():
    major = gear_gap_engine.__version__.split(".")[0]
    assert_bundle_compatible(f"{major}.99.99")
    assert_bundle_compatible(f"{major}.0.0")


def test_a_bundle_recording_no_version_is_refused_not_trusted():
    """A bundle predating this contract says nothing about how its keys were
    written. "Assume it is fine" is exactly the silent skew the version exists
    to prevent, and rebuilding is cheap."""
    with pytest.raises(IncompatibleBundle) as caught:
        assert_bundle_compatible(None)
    assert "no engine version" in str(caught.value)


def test_an_unparseable_version_is_refused():
    with pytest.raises(IncompatibleBundle):
        assert_bundle_compatible("not-a-version")


def test_the_version_is_semver_shaped():
    parts = gear_gap_engine.__version__.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)
