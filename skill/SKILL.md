---
name: agent-skill-manager
description: Manage versioned Agent Skills from a GitHub catalog. Use when the user asks to check for skill updates, install or roll back a stable skill version, prepare a skill release, or publish an explicitly approved GitHub Release. Do not use for ordinary skill authoring that does not involve distribution or version management.
---

# Agent Skill Manager

Treat published, stable GitHub Releases as the only authoritative install source.
Never install from a branch, untagged commit, pull request, draft, or prerelease.

The user's instructions take precedence over this skill. This skill does not grant
permission to mutate local skills or GitHub repositories.

## Choose the mode

- For checking, installing, or rolling back, read
  [references/update-workflow.md](references/update-workflow.md).
- For preparing or publishing a release, read
  [references/publish-workflow.md](references/publish-workflow.md).
- When adding a new Agent or operating system, read
  [references/compatibility.md](references/compatibility.md).

## Core commands

Use `scripts/skill_manager.py` for installed-skill operations:

```text
python scripts/skill_manager.py check --catalog <path-or-url> --agent codex
python scripts/skill_manager.py install <skill-id> --catalog <path-or-url> --agent codex
python scripts/skill_manager.py rollback <skill-id> --version <version>
```

Use `scripts/release_tool.py` for release operations:

```text
python scripts/release_tool.py validate --skill-dir <repo>/skill
python scripts/release_tool.py prepare --repo-dir <repo> --version 1.2.0 --summary "..."
python scripts/release_tool.py draft --repo-dir <repo> --version 1.2.0 --repository owner/repo
python scripts/release_tool.py publish --repository owner/repo --skill-id <id> --version 1.2.0
```

Resolve `python` to an available Python 3.11+ executable. The scripts use only the
standard library. Do not install missing runtimes without the user's permission.

## Non-negotiable controls

- A scheduled run may execute `check` only. It must not install, overwrite, roll
  back, commit, push, create a draft, or publish.
- Show the update list and change summary before requesting installation approval.
- Install one skill at a time. Pass the exact confirmation token printed by the CLI
  only after the user approves that skill and version.
- If the CLI reports local modifications, show the digest and obtain a separate
  overwrite approval before continuing.
- Verify the release asset SHA-256 and reject unsafe ZIP paths or symbolic links.
- Reject unsupported Agent, operating system, architecture, or declared dependency.
- Keep the previous version and state record so rollback remains available.
- Before publishing, show the source diff, validation result, semantic version,
  release summary, and package inventory.
- Creating a Draft Release and publishing it are separate externally mutating
  actions. Obtain authorization for each. Publishing requires the exact token
  printed by the CLI.
- Never put GitHub tokens in skill files, manifests, command output, or repositories.
  Use GitHub CLI authentication or an environment-provided token.

If a required tool or capability is missing, stop and report the exact requirement.
Do not substitute an approximate or less secure workflow.

