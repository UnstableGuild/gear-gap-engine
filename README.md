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
  "gear-gap-engine @ git+ssh://git@github-liqiud/UnstableGuild/gear-gap-engine@v1.0.0",
]
```

`github-liqiud` is the SSH host alias this machine uses for the guild account and
is what this repo's own remote points at; the form above is the one that has
actually been installed and imported, not the one that looks right. Anywhere
without that alias — a CI runner, an image build — use
`git+ssh://git@github.com/UnstableGuild/…` with a deploy key, and check it
resolves before relying on it.

**Pin a tag, never a branch.** A floating `@main` reintroduces exactly the skew
the version contract exists to prevent, silently, at whatever moment a service
happens to rebuild its image.

## Consuming it from CI — READ THIS BEFORE CREATING A NEW SERVICE

This repo is **private**, so a build anywhere other than a developer's machine
needs credentials to fetch it. Actions' `GITHUB_TOKEN` is scoped to its own
repository and **cannot** clone this one, so every consumer needs the deploy key
below. Enabled org-wide and provisioned on 2026-09-02, approved by John; the
alternatives were a person-scoped PAT (broader, and it expires) or making this
repo public (which he declined).

**Adding a new consumer repo — all of it:**

1. The read-only deploy key already exists on this repo, one per consumer, named
   for its consumer: `gear-gap-reference CI (read-only)`. **Add a new key named
   for the new consumer.** Six identically-named keys are unrotatable in
   practice because nobody can tell which is which.

   ```
   ssh-keygen -t ed25519 -N '' -C '<consumer> CI -> gear-gap-engine (read-only)' -f /tmp/k
   gh repo deploy-key add /tmp/k.pub --repo UnstableGuild/gear-gap-engine      --title '<consumer> CI (read-only)'
   gh secret set ENGINE_DEPLOY_KEY --repo UnstableGuild/<consumer> < /tmp/k
   rm -f /tmp/k /tmp/k.pub          # the private half must not outlive this
   ```

2. **Secret name: `ENGINE_DEPLOY_KEY`**, on the *consumer* repo. It holds the
   **private** half; the public half is the deploy key here. Read-only always —
   consumers fetch, they never push.

3. The pin uses the `github-liqiud` SSH **host alias**, which exists in a
   developer's `~/.ssh/config` and nowhere else. CI and the Dockerfile must both
   teach that alias to their environment, or the same pin that works locally
   fails everywhere else. `gear-gap-reference` is the worked example.

**WHAT IT LOOKS LIKE WHEN THE SECRET IS MISSING**, because this is the part that
costs an hour: `pip install` fails cloning the dependency with a permission or
host-key error that reads as a **network problem**, not a credential one. The
build looks broken, the registry looks down, and nothing says "this repo has no
`ENGINE_DEPLOY_KEY`". `gear-gap-reference`'s workflow checks for the secret
first and fails with that sentence, so copy that step rather than debugging the
symptom.

**These keys are not rotated on a schedule and must not be.** There is no
automation for it, and a key that silently expires is exactly the failure this
project keeps paying for. Rotation is a deliberate act.

## Cloning a service repo — CHANGE ALL OF THIS

Service repos are made by copying a neighbour, because that is faster than
assembling one. The copy arrives carrying the neighbour's identity, and **most of
it fails loudly while one item fails silently**: two services sharing a published
database port on one machine means the new one quietly talks to the old one's
database. That costs an evening; everything else on this list costs minutes.

This lives here because every new service must read this file anyway for the
deploy key, so it is the one document that cannot be missed.

| Change | Where | If you forget |
|---|---|---|
| **Published database port** | `compose.yaml` `ports:` and the `sed` in `.mise.toml`'s `test-db` | **SILENT.** The new service reads and writes its neighbour's database |
| **Dead config and fixtures from the neighbour** | any module or fixture the clone didn't ask for — a config class for a concern this service doesn't have, `conftest.py` fixtures pointing at a `fixtures/` directory that was never copied | **SILENT, and worse than the port row: it is inert until someone reads it.** Nothing breaks, nothing fails a test, and a future reader believes the service has a token path or fixtures it does not. Grep the diff against the neighbour for anything your new service has no reason to import |
| **Removing or changing a dependency** | `pyproject.toml` | **`pip install -e .` never uninstalls.** Dropping a line from `dependencies` leaves the package sitting in your existing venv, so the local gate stays green while it is quietly gating an environment that no longer matches the file. Verify by rebuilding the venv from scratch (`rm -rf .venv-*/`, reinstall) before trusting a removal — CI already does this on every run, which is why gear-gap-intent's stage 3 passed locally and failed there: `httpx` looked unused by this service's own code and was removed entirely, but `fastapi.testclient` (used by the test suite) needs an HTTP client to exist regardless. "This service's code never touches a third party" and "this repo needs no HTTP client dependency" are different claims — the fix was `httpx` back as a **dev-only** dependency, not a runtime one |
| Package name | `pyproject.toml`, `src/<pkg>/`, every import | Loud, immediately |
| `test-db` task | `.mise.toml` — the copy already has one; **edit it, do not append** | Loud: mise refuses a duplicate key |
| Schema and role names | the migration, `roles.py`/`reader.py`, `.env.example` | Two services fighting over one role name |
| `ENGINE_DEPLOY_KEY` | `gh secret set` on the new repo, plus a **new** deploy key here named for it | A clone error in CI that reads as a network problem |
| Image name in CI | `.github/workflows/build.yaml` `IMAGE:` | The new service overwrites its neighbour's published image |
| Repo name and description | `gh repo create` | Cosmetic |
| `.env` | regenerate — never copy a neighbour's passwords | Shared credentials across services |
| **Keep `mise run gate`** | `.mise.toml` — every repo has it; do not drop it | See below |

**`mise run gate` runs ruff, mypy and the tests bare, in order, stopping at the
first failure.** It exists because a gate piped into `tail` reports the
*filter's* exit status, so a failing lint reads as success and a broken commit
gets made while the output looks fine — that happened three times in one day.
The fix is not a stronger rule but a shape: the short output somebody wanted is
what this already produces, so there is nothing left to pipe. **Run it bare and
let it fail.**

**Why a checklist and not a template repo.** A template is a thing to maintain,
it drifts from whatever the newest service actually does, and it would carry the
same stale ports and names into every clone — it makes this list necessary
rather than unnecessary. The list is ten rows and lives next to the credential
step nobody can skip.

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
