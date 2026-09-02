# gear-gap-engine

The gear-gap rules, as a package. Pure: stdlib only, no network, no config, no
database. Every function gives the same answer for any character on any realm,
which is the test for whether a rule belongs here at all.

Extracted from `unstable-gear-gap`, which keeps its own copy and keeps serving.
The two are expected to diverge; the live app is frozen except for bugs.

## Why it is a library and not a service

Putting a pure function behind HTTP adds latency and a failure mode for nothing.
The guarantee that the single-character and roster paths can never disagree
about what a gap is holds only because both call this same code — which is now
true only if both depend on the same **major** version.

## The version contract, which is the whole reason this is versioned

`slot_key` and `fingerprint` decide how items are **keyed into** a reference
bundle. The matching logic reads those keys back. A builder on one version and a
reader on another writes under one scheme and reads under another: every lookup
misses, every slot reports as unmatched, and nothing anywhere is unhealthy.

That failure is silent and confident, which makes it worse than a crash. So the
bundle records the engine version it was built with, and the reader refuses what
it cannot trust:

```python
from gear_gap_engine import assert_bundle_compatible

assert_bundle_compatible(bundle["engine_version"])   # raises IncompatibleBundle
```

A bundle recording **no** version is refused rather than trusted — nothing is
known about how its keys were written, and rebuilding is cheap.

| Bump | Means |
|---|---|
| MAJOR | anything changing how an item is keyed or matched: `slot_key`, `fingerprint`, the normaliser, the slot vocabulary, source classification. Existing bundles are unreadable, not merely older. |
| MINOR | additive API — a new export, a new optional argument. Keys unchanged, bundles stay readable. |
| PATCH | fixes changing no key and no public signature. |

The trap: *"it is only a small change to the normaliser"* is a **major** change,
because the bundle on disk was written with the old one.

## Consuming it

Private repo, so a git+ssh dependency pinned to a tag — no registry to run:

```toml
dependencies = [
  "gear-gap-engine @ git+ssh://git@github.com/UnstableGuild/gear-gap-engine@v1.0.0",
]
```

**Pin a tag, never a branch.** A floating `@main` reintroduces exactly the skew
the version contract exists to prevent, silently, at whatever moment a service
happens to rebuild its image.

## Public surface

`__all__` in `__init__.py` is curated, not "whatever happens to be importable" —
everything named there is promised not to break within a major. Nothing with a
leading underscore is exported.

`assert_sources_distinguishable` is the notable one. The bundle loader used to
import the private `_match_key` to check that no source name is a substring of
another once squashed. That made the caller know *how* names are normalised in
order to guard an assumption it did not own. The engine now exposes the
question, so the normalisation can change without breaking a consumer.

## Development

```
mise run bootstrap      # venv + deps + pre-commit
mise run test
mise run lint
mise run type-check
```
