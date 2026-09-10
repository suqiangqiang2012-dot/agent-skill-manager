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

## Repository layout

- `skill/`: canonical Agent Skill source.
- `tests/`: standard-library Python tests.
- `release.json`: generated package targets.

## Validation

```text
python -m unittest discover -s tests -v
python skill/scripts/release_tool.py validate --skill-dir skill
```

No third-party Python package is required by the runtime tools.

