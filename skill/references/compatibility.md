# Compatibility

## Validated adapters

| Agent | Windows | macOS | Install root | Reload |
|---|---|---|---|---|
| Codex | Supported | Supported | `CODEX_HOME/skills` or `~/.codex/skills` | Required |
| WorkBuddy | Supported (5.5.4+) | Not yet validated | `WORKBUDDY_HOME/skills` or `~/.workbuddy/skills` | Hot reload; restart not required |

Both adapters install the native Agent Skill directory containing `SKILL.md`.
A package may be declared `any` architecture when it contains no native binaries.

## WorkBuddy Windows adapter

The validated WorkBuddy installation uses:

- skill root: `~/.workbuddy/skills`;
- app version: `%LOCALAPPDATA%/Programs/WorkBuddy/resources/install-manifest.json`;
- built-in Python: `~/.workbuddy/binaries/python/envs/default/Scripts/python.exe`;
- native file watching under the skill root, so copied skill changes are hot-reloaded.

A release target may declare `minimum_agent_version`. The manager refuses
installation when the installed WorkBuddy version cannot be detected or is older.

## Planned adapters

Claude Code, Cursor, OpenClaw, DeepSeek Harness, and WorkBuddy on macOS remain
planned until their adapter has:

- a verified installation root or supported import mechanism;
- metadata conversion rules;
- reload behavior;
- version and dependency detection;
- an install/rollback test on each declared operating system.

Until then, the manager must report `unsupported adapter` or no compatible package
and refuse installation.

## Package selection

The manager selects the most specific compatible package:

1. exact Agent + exact OS + exact architecture;
2. exact Agent + exact OS + `any` architecture;
3. exact Agent + all declared operating systems + `any` architecture.

It never substitutes a package built for another Agent.

## Install roots

An explicit `--install-root` always takes precedence.

For Codex, the fallback order is:

1. `CODEX_HOME/skills`;
2. `~/.codex/skills`.

For WorkBuddy, the fallback order is:

1. `WORKBUDDY_HOME/skills`;
2. `~/.workbuddy/skills`.

## State isolation

Installed versions, backup history, and rollback state are keyed by both Agent and
skill ID. Installing the same skill in Codex and WorkBuddy must not overwrite either
Agent's state.

## Requirements

Requirements are executable names or human-verifiable capabilities. Executables are
checked on `PATH`. Human-verifiable capabilities are reported and installation is
refused until the Agent can confirm them.
