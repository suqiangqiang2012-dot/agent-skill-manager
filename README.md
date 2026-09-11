# Agent Skill Manager

Public source repository for checking, installing, rolling back, preparing, and
publishing stable Agent Skill releases.

## Rules

- GitHub stable Releases are the only install source.
- Scheduled checks are read-only.
- Install and rollback require exact per-skill confirmation.
- Draft creation and stable publication require separate confirmation.
- Package integrity is verified before extraction.
- Unsupported adapters fail closed.

## Supported adapters

- Codex: Windows and macOS.
- WorkBuddy: Windows 5.5.4 or later; uses the native `~/.workbuddy/skills` root
  and WorkBuddy's bundled Python runtime.
- Other adapters remain fail-closed until validated.
## Repository layout

- `skill/`: canonical Agent Skill source.
- `skill/assets/skill-repo-template/release.json`: portable starting point for a
  new skill repository's release targets.
- `docs/architecture.md`: repository, release, compatibility, and catalog model.
- `tests/`: standard-library Python tests.
- `release.json`: generated package targets.

## New skill repositories

Copy the bundled release template, replace its placeholder skill ID, and explicitly
confirm the target Agents and operating systems before validation. Remove targets
that have not been verified for that skill. The current template offers Codex on
Windows and macOS plus WorkBuddy 5.5.4 or later on Windows; WorkBuddy on macOS is
not yet validated.

## Validation

```text
python -m unittest discover -s tests -v
python skill/scripts/release_tool.py validate --skill-dir skill
```

No third-party Python package is required by the runtime tools.

