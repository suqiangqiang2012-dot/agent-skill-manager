# Update workflow

## Check

Run `skill_manager.py check` against the configured local or remote catalog.
The command is read-only apart from its local report cache and state directory.

Display one row per skill:

- installed version;
- latest stable version;
- update status;
- compatibility;
- release summary.

Entries whose repository is not configured remain visible as
`local-preparation`; do not treat them as errors.

## Install

Run the install command once without a confirmation token. It resolves the stable
Release, selects the compatible package, and prints the exact token required.

Show the user:

- skill ID;
- installed and proposed versions;
- release summary;
- target Agent, operating system, and architecture;
- requirements;
- package digest.

After approval, repeat the command with:

```text
--confirm <skill-id>@<version>
```

If the installed tree differs from the state digest, the command refuses to
continue and prints an overwrite digest. Explain that local changes will be
replaced. Continue only after the user approves, adding:

```text
--overwrite-modified <digest-prefix>
```

Do not infer approval from an earlier request to check for updates.

## Rollback

List available backups:

```text
python scripts/skill_manager.py backups <skill-id> --agent <agent>
```

Run rollback once with `--agent <agent>` and without confirmation, then show the
proposed target. After approval, repeat the same command with:

```text
--confirm rollback:<skill-id>@<version>
```

Rollback restores the selected backup and records the resulting installed state.

## Weekly check

The preferred weekly command is:

```text
python scripts/skill_manager.py check --catalog <catalog> --agent <agent> --cache-report
```

Use the Agent's native scheduler when it supports a read-only recurring task. If it
does not, report that weekly scheduling is unsupported and retain manual checking.
Do not silently create an operating-system scheduled task as a substitute.

## Private repositories

The CLI first checks `GITHUB_TOKEN`, then `GH_CLI_PATH`, then GitHub CLI on
`PATH`. Tokens are used only in request headers and are never persisted by the
manager.

If a private repository cannot be read, stop and ask the user to authenticate with
GitHub CLI. Do not request that the user paste a token into chat.

