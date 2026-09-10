# Compatibility

## Supported in phase 1

| Agent | Windows | macOS | Install mode |
|---|---|---|---|
| Codex | Supported | Supported | Copy to the configured Codex skills root |

The Codex package is `any-os` when it contains no native binaries.

## Planned adapters

Claude Code, Cursor, OpenClaw, WorkBuddy, and DeepSeek Harness remain planned until
their adapter has:

- a verified installation root or supported import mechanism;
- metadata conversion rules;
- reload behavior;
- version and dependency detection;
- an install/rollback test on each declared operating system.

Until then, the manager must report `unsupported adapter` and refuse installation.

## Package selection

The manager selects the most specific compatible package:

1. exact Agent + exact OS + exact architecture;
2. exact Agent + exact OS + `any` architecture;
3. exact Agent + all declared operating systems + `any` architecture.

It never substitutes a package built for another Agent.

## Install roots

For Codex, the order is:

1. explicit `--install-root`;
2. `CODEX_HOME/skills`;
3. `~/.codex/skills`.

Other Agent roots must be supplied by a validated adapter. Do not guess them.

## Requirements

Requirements are executable names or human-verifiable capabilities. Executables are
checked on `PATH`. Human-verifiable capabilities are reported and installation is
refused until the Agent can confirm them.

