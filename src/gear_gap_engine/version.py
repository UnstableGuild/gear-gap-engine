"""The engine's version, and the compatibility rule bundles are held to.

WHY A BUNDLE RECORDS THIS AT ALL. `slot_key` and `fingerprint` decide how items
are KEYED INTO a reference bundle, and the matching logic reads those keys back.
A builder on one version and a reader on another writes under one scheme and
reads under another: every lookup misses, every slot reports as unmatched, and
nothing anywhere is unhealthy. That failure is silent and confident, which makes
it worse than a crash -- so the version travels with the data and the reader
refuses what it cannot trust.

THE SEMVER RULE, STATED SO IT IS NOT A JUDGEMENT CALL LATER:

    MAJOR  anything that changes how an item is keyed or matched --
           slot_key, fingerprint, _match_key, the slot vocabulary,
           the source-classification rules. A bundle built by a
           different major is unreadable, not merely older.
    MINOR  additive API: a new export, a new optional argument.
           Keys unchanged, so bundles stay readable across it.
    PATCH  fixes that change no key and no public signature.

The trap to avoid: "it is only a small change to the normaliser" is a MAJOR
change, because the bundle on disk was written with the old one.
"""

from __future__ import annotations

__version__ = "1.0.0"


class IncompatibleBundle(RuntimeError):
    """A bundle built by an engine this one cannot read."""


def _major(version: str) -> int:
    head = version.strip().split(".", 1)[0]
    if not head.isdigit():
        raise IncompatibleBundle(f"unreadable engine version: {version!r}")
    return int(head)


def assert_bundle_compatible(built_with: str | None) -> None:
    """Refuse a bundle this engine cannot read. Loud, never a warning.

    `None` is REFUSED rather than trusted. A bundle carrying no engine version
    predates this contract, so nothing is known about how its keys were written
    -- and "assume it is fine" is exactly the silent-skew failure the version
    exists to prevent. Rebuilding is cheap; a confidently wrong gap list is not.

    Same major passes. Minor and patch are additive by the rule above, so a
    reader may be older or newer than the builder within one major.
    """
    if built_with is None:
        raise IncompatibleBundle(
            "this bundle records no engine version, so how its item keys were "
            f"written is unknown; rebuild it with gear-gap-engine {__version__}"
        )
    if _major(built_with) != _major(__version__):
        raise IncompatibleBundle(
            f"bundle was built with gear-gap-engine {built_with}, which is a "
            f"different major version from {__version__}; item keys are not "
            "comparable across a major, so this bundle must be rebuilt"
        )
