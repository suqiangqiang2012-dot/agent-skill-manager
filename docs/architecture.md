# Architecture

## Source of truth

Each skill has one independent GitHub repository and one canonical `skill/`
directory. Platform packages are generated artifacts. They must not be edited by
hand or used as the source for a later release.

The public catalog contains metadata and repository coordinates. Skill contents
remain private when their repository is private.

## Repository model

```text
personal GitHub account
├── agent-skill-catalog
├── agent-skill-manager
├── skill-public-example
└── skill-amies-ppt-template       private
```

The local `agent-skill-hub` workspace coordinates these repositories. It is not
the distribution source.

## Release states

```text
local edit
  -> validated candidate
  -> Draft Release
  -> explicit approval
  -> stable immutable Release
  -> update available
  -> per-agent installation approval
```

A commit on `main`, a branch, a pull request, or a draft is not an installable
version. Only a published, non-prerelease GitHub Release with a semantic version
tag is installable.

## Package dimensions

Packages are split only when necessary:

- `any-os`: instructions, references, templates, images, or portable scripts.
- agent-specific: metadata or layout differs by Agent.
- OS/architecture-specific: native binaries or non-portable scripts are present.

Current verified package targets:

```text
<skill>-v<version>-codex-any.zip
<skill>-v<version>-workbuddy-windows-any.zip
```

## Compatibility

Every release declares:

- Agent name and minimum supported version, when known.
- Operating systems.
- CPU architectures.
- Required executables, fonts, applications, and environment capabilities.
- Installation mode and reload requirements.

Unknown or unsupported conditions fail closed. Codex is verified on Windows and
macOS. WorkBuddy 5.5.4 or later is verified on Windows; WorkBuddy on macOS is not
yet validated. Declaring a target requires an explicit compatibility decision for
that skill; template entries are not evidence that a skill works everywhere.

## Update behavior

Each Agent maintains independent local state. Different Agents and devices may
remain on different stable versions.

Scheduled checks are read-only: read the catalog, query stable Releases, compare
installed state, and cache a human-readable update list. Installation requires an
exact per-skill confirmation. A modified local skill also requires a separate
overwrite confirmation.

## Publication behavior

Only one Agent edits a skill at a time. The editing Agent:

1. Modifies canonical source.
2. Confirms intended Agent and operating-system targets.
3. Runs structural and integrity validation.
4. Generates packages, manifest, checksums, and release notes.
5. Revalidates every declared target and package before Draft creation.
6. Shows the diff, semantic version, summary, and package inventory.
7. Creates a Draft Release after authorization.
8. Publishes the Draft only after a separate confirmation.
9. Audits catalog registration and runs read-only discovery checks.

For a new stable skill, prepare a missing catalog entry for review. For an existing
catalog entry, a version-only release does not change the catalog. Catalog commit
and push are separately authorized.

## Privacy

Public metadata may describe a private skill. Private skill source, references,
scripts, and assets remain in the private repository. The catalog never embeds
private files or release assets.
