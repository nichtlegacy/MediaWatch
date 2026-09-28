# AGENTS.md

MediaWatch is a discord.py bot that publishes one live dashboard for **either** Plex
**or** Jellyfin into a Discord channel. Python 3.12, no database, state is files under
`data/`. Everything runs inside cogs loaded by `main.py`.

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the human version of the rules below, and
[docs/reference/architecture.md](docs/reference/architecture.md) when a change touches
the runtime shape.

## Commands

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # includes requirements.txt

.venv/bin/python -m pytest                      # full suite, must be green
.venv/bin/python -m pytest tests/unit/shared/test_formatters.py -q   # one file
.venv/bin/ruff check .                          # must pass
.venv/bin/ruff format .                         # before committing

.venv/bin/pip install -r requirements-docs.txt
.venv/bin/mkdocs build --strict                 # a broken link fails the build
.venv/bin/mkdocs serve
PYTHON=.venv/bin/python scripts/build_pages.sh --serve   # landing page + docs, as published
```

Prefer the file-scoped pytest run while iterating; run the full suite before reporting
done. Do not run `python main.py`: it needs real Discord and media server credentials.

## Layout

```text
main.py                     logging, config migration, env validation, cog loading
cogs/media_core/shared/     platform-agnostic: protocol, models, dashboard, config
cogs/media_core/plex/       PlexCore cog, PlexMediaService, Plex + Tautulli clients
cogs/media_core/jellyfin/   JellyfinCore cog, JellyfinMediaService, Jellyfin client
cogs/sabnzbd.py             optional download block
cogs/uptime.py              optional Uptime Kuma block
cogs/user_mapping.py        /mapping commands
data/config.yaml.example    the only tracked file in data/
tests/unit/                 mirrors the package layout
docs/                       MkDocs Material source; site/ is build output
landing/                    static landing page, published at the Pages root; docs go to /docs/
overrides/                  MkDocs theme override: link-preview tags for the docs
```

## Architecture rules

These are invariants, not preferences. Breaking one is a bug even if the tests pass.

- **`shared/` never imports from `plex/` or `jellyfin/`.** The dependency points inward
  only. That is what lets one dashboard builder serve both platforms.
- **Exactly one platform is loaded at runtime**, chosen by `media_server.type`. Never add
  a code path that assumes both are live. Both write the same
  `data/dashboard_message_id.json` and both call `bot.change_presence()`.
- **Keep the `MediaService` protocol narrow** (`shared/base_service.py`). A capability
  only one platform has (Tautulli statistics, for example) stays inside that platform's
  tree instead of becoming an optional method the other side stubs out.
- **Cross-platform work is normalized into the dataclasses in `shared/models.py`**
  (`ServerStatus`, `ActiveStream`, `LibraryStats`). Past that boundary, code is
  platform-agnostic and must stay that way.
- **Fix a platform bug in `shared/` when the logic is shared.** If you touch
  `plex/`, check whether `jellyfin/` has the same bug, and say which you chose and why.

## Code conventions

- **Never `print()`.** Every module takes `logging.getLogger("mediawatch_bot.<dotted.path>")`;
  ruff `T20` enforces the ban.
- **No blocking calls inside `async def`.** `plexapi` is synchronous, so Plex calls go
  through `asyncio.to_thread`; Jellyfin uses `aiohttp` throughout. ruff `ASYNC` catches
  the network cases.
- **All file writes go through `write_text_atomic()` / `write_json_atomic()`**
  (`shared/config_utils.py`). A restart mid-write must leave the old file or the new one,
  never a truncated `config.yaml`.
- **Both loops swallow and log their own exceptions.** A failing tick is skipped, never
  fatal. Keep it that way.
- Line length 100, double quotes, formatter handles wrapping (`E501` is off). Type hints
  on new public functions; docstrings say *why*, not what the signature already says.
- The ruff rule set is deliberately narrow. Do not widen it as a side effect of another
  change; that is its own pull request.

## Configuration

- Runtime secrets live in `.env`; behaviour lives in `data/config.yaml`. Neither is
  tracked. `.gitignore` ignores every `.env*` except the example; do not fight that.
- A new option needs three things: a default in `load_config()`
  (`cogs/media_core/shared/config.py`), an entry in `data/config.yaml.example`, and a row
  in `docs/configuration/reference.md`.
- **New options default to current behaviour.** A running bot must keep working after an
  update without a config edit.

## Tests

- `tests/unit/` mirrors the package layout (`plex/`, `jellyfin/`, `shared/`).
  `asyncio_mode = auto`, so `async def test_...` needs no decorator.
- No real Plex or Jellyfin server is needed; both are mocked. If a test would need one,
  the seam is wrong.
- New non-trivial logic needs a test: a branch, a parser, a format helper, anything
  touching authorization. A rename does not.
- A test that passes whatever the code does is worse than no test. Assert the behaviour,
  not the call.

## Docs

- The site is MkDocs Material under `docs/`, published under `/docs/` by
  `.github/workflows/docs.yml`; the landing page in `landing/` sits at the root.
  `site/` and `_site/` are generated: never edit them, never commit them.
- The Discord demo in `landing/app.js` copies the bot's output strings (dashboard, stream
  blocks, stream details, stats). When a formatter's output changes, update the demo too.
- **No real secrets or identifiers in docs, examples or screenshots.** No real tokens
  (not even truncated), no real Discord IDs, no real internal hostnames or IPs. Use
  `192.168.1.10`, `plex.example.local`, `http://plex:32400`.
- Quote error messages **verbatim** so they can be grepped in a log.
- Every claim must be backed by the code. Second person, active voice, no marketing.
- Config blocks are complete and runnable, with the default documented.

## Git, commits, releases

- Branch off `main`: `feature/…`, `fix/…`, `docs/…`, named after what it does.
- [Conventional Commits](https://www.conventionalcommits.org/), scope = the area touched
  (`plex`, `jellyfin`, `shared`, `sabnzbd`, `uptime`, `mapping`, `config`, `dashboard`,
  `docker`, `main`): `fix(sabnzbd): keep the download name when a keyword starts it`.
- One logical change per commit. Never mix a reformat into a bug fix.
- The commit type drives the changelog: release-please maintains `CHANGELOG.md` and
  `version.py` from the commits on `main`. **Never bump the version by hand.**
- `feat`/`fix`/`perf`/`refactor`/`docs`/`build` are visible in the changelog;
  `test`/`chore`/`ci`/`style` are hidden.

## Boundaries

Ask before doing any of these:

- Committing, pushing, opening or merging a PR, or tagging a release.
- Adding a runtime dependency. The list in `requirements.txt` is short on purpose; use
  the stdlib or an already-installed package first.
- Widening the ruff rule set, changing CI workflows, or touching `Dockerfile` /
  `entrypoint.sh` privilege handling.
- Reformatting or refactoring files the task did not otherwise touch.

Never read, write or commit `.env`, `data/config.yaml`, `data/*.json` or `logs/`: they
hold real credentials and real user data. Security issues go to
[SECURITY.md](SECURITY.md), never into a public issue.
