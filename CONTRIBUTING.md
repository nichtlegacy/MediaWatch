# Contributing to MediaWatch

MediaWatch is maintained by one person in their spare time. That shapes what
works well here: small, focused pull requests get reviewed. Large rewrites and
"I refactored everything" branches usually do not.

Bug reports are just as welcome as code. A good bug report is often more useful
than a patch.

## Setup

Python 3.12 is what the project is developed and shipped against
(`python:3.12-slim` in the Dockerfile).

```bash
git clone https://github.com/nichtlegacy/MediaWatch.git
cd MediaWatch

python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # pulls in requirements.txt
```

`requirements-dev.txt` adds `pytest`, `pytest-asyncio` and `ruff` on top of the
runtime dependencies.

You do **not** need a running Plex or Jellyfin server to work on the code. The
test suite mocks both. You only need real credentials if you want to run the
bot itself, in which case copy `.env.example` to `.env` and
`data/config.yaml.example` to `data/config.yaml`.

Neither `.env` nor `data/config.yaml` is tracked by git, and `.gitignore`
ignores every `.env*` file except the example. Do not fight that.

## Tests

```bash
.venv/bin/python -m pytest
```

The suite is expected to be green. A red suite means the change is not finished.

Tests live in `tests/unit/` and mirror the package layout
(`tests/unit/plex/`, `tests/unit/jellyfin/`, `tests/unit/shared/`).
`pyproject.toml` sets `asyncio_mode = auto`, so `async def test_...` works without
a decorator.

New non-trivial logic needs a test. "Non-trivial" means: a branch, a parser, a
format helper, anything touching authorization. A one-line rename does not.

## CI and publishing

GitHub and Forgejo use the same `.github/workflows/ci.yml`. Do not add a
`.forgejo/workflows` directory: Forgejo would prefer it and stop reading the
shared workflows.

**CI / Validate** runs Ruff, the full Python 3.12 test suite, the website build,
a Docker build and an offline container smoke test. The smoke test runs the
real entrypoint with default IDs, custom PUID/PGID and an explicit non-root
user, checking imports and file permissions without Discord credentials.

| Workflow | When it runs |
| --- | --- |
| **CI** (both hosts) | PRs to `main`/`dev`, pushes to those branches, or manual runs |
| **Pages** (GitHub) | Publishes the checked `main` commit after successful CI |
| **Prepare release** (GitHub) | Updates the release PR after successful `main` CI; calls the container workflow when a release is created |
| **Publish container** (GitHub) | Publishes the checked branch commit after CI; releases and manual runs repeat Python and container checks |

Forgejo CI also publishes `prod` and `sha-<12-character-commit>` after checks on
`main`, except on PRs. GitHub's branch images use `latest` for `main` and `dev`
for `dev`. Release images use their version tag; only stable releases also
update `latest`.

Configure branch protection to require **Validate**. Keep GitHub's default
workflow token permissions set to **Read repository contents and packages**:
the shared CI cannot declare `permissions`, which Forgejo does not support.
GitHub-only publishing workflows declare their required write permissions.
They use `workflow_run` for automatic publishing, which Forgejo does not emit;
server guards also prevent execution on Forgejo for release/manual events.
Forgejo may still show a permissions warning for such a manually triggered,
skipped GitHub-only workflow; the shared CI contains no permissions fields.

Release Please uses `GITHUB_TOKEN`. Its generated PRs do not automatically
trigger CI; close and reopen the PR as a maintainer to trigger checks before
merging. Published release images still run their own checks. If this manual
step becomes inconvenient, configure a GitHub App token for Release Please.

Forgejo uses the `python-3.12` runner with Docker access. Bare action names resolve
through the instance's `DEFAULT_ACTIONS_URL` (normally `https://data.forgejo.org`);
the pinned checkout commit is available there and on GitHub. Set the repository
variable `REGISTRY_HOST` to the registry hostname (without a scheme or path), and
the secret `REGISTRY_TOKEN` to a token with package write access. `REGISTRY_USERNAME`
is optional and defaults to the repository owner; set it when the token belongs
to a different account. PR checks do not need registry credentials.

To run the container check locally, build an image and pass its name:

```bash
docker build -t mediawatch:check .
bash scripts/check_container.sh mediawatch:check
```

## Lint and format

`ruff` is the only tool, config in `pyproject.toml`:

```bash
.venv/bin/ruff check .      # must pass
.venv/bin/ruff format .     # before committing
```

The rule set is deliberately narrow (pyflakes, bugbear, async, logging, no
stray `print`). If you think a rule should be added, open an issue first: a
new rule that lights up 200 existing lines is its own pull request, not a
side effect of yours.

Line length is 100. `E501` is off; the formatter handles wrapping.

## Branches and commits

Branch off `main`, name it after what it does:

```
feature/jellyfin-support
fix/sabnzbd-queue-url
docs/setup-guide
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(jellyfin): show configured library names in stream details
fix(sabnzbd): keep the download name when a keyword starts it
refactor(plex): drop the legacy plex_handler aliases
docs(migration): add the 1.x to 2.0 upgrade path
```

Types in use: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `build`,
`chore`. Scopes are the area you touched: `plex`, `jellyfin`, `shared`,
`sabnzbd`, `uptime`, `mapping`, `config`, `dashboard`, `docker`, `main`.

One logical change per commit. Do not mix a reformat into a bug fix; the diff
becomes unreviewable and that is the fastest way to have a PR sit unread.

## What makes a good pull request

- It does one thing, and the title says which.
- Tests pass, `ruff check` passes.
- It does not reformat lines it did not otherwise touch.
- Behaviour of existing setups does not change silently. New options default to
  the current behaviour, so a running bot keeps working after an update without
  a config edit.
- If it adds or changes a config option, `data/config.yaml.example` documents it
  and the README stays truthful.
- If it changes something a 1.x user would trip over, `docs/operations/upgrading-from-1x.md` says so.

For anything larger than a bug fix, open an issue first and describe the idea.
It is much cheaper to say "not a direction I want to take" before you write the
code than after.

## Both platforms

The bot supports Plex **or** Jellyfin, selected by `media_server.type`. A
change to one platform is not automatically wanted on the other, but a
divergence should be deliberate. If you fix a formatting bug in
`cogs/media_core/plex/`, check whether `cogs/media_core/jellyfin/` has the same
bug, and say in the PR which one you chose and why.

Shared logic belongs in `cogs/media_core/shared/`, not copied into both trees.

## Security

Do not open a public issue for a security problem. See [SECURITY.md](SECURITY.md).
