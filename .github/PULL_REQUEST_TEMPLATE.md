## What this changes

<!-- One or two sentences. If it fixes an issue, write "Fixes #123". -->

## Why

<!-- The problem, not the diff. -->

## How it was tested

<!-- What you actually ran. "Tests pass" alone is fine for a pure refactor. -->

- [ ] `.venv/bin/python -m pytest` is green
- [ ] `.venv/bin/ruff check .` is clean
- [ ] `.venv/bin/ruff format .` was run

## Checklist

- [ ] One logical change; no unrelated reformatting
- [ ] Existing installs keep working without a config edit (new options default
      to the current behaviour)
- [ ] New or changed config options are documented in `data/config.yaml.example`
- [ ] New non-trivial logic has a test in `tests/unit/`
- [ ] If it touches one platform, I checked whether the other has the same issue
- [ ] No secrets, tokens or real config values in the diff
