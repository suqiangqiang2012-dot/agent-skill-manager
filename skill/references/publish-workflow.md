# Publish workflow

## Authority boundary

A local skill edit is not permission to publish. The editing Agent may prepare
files and a local candidate, but GitHub mutations require explicit authorization.

Only one Agent may edit a given skill at a time.

## Canonical source

Edit only the repository's `skill/` directory and release configuration.
Never edit a generated ZIP or reconstruct the next source version from a package.

## Validate

Run:

```text
python scripts/release_tool.py validate --skill-dir <repo>/skill
```

Validation checks:

- required `SKILL.md`;
- supported frontmatter keys and required name/description;
- unfinished placeholders;
- local references from `SKILL.md`;
- readable files and complete file inventory.

This workflow does not run a representative user task unless separately requested.

## Prepare

Choose a semantic version:

- patch: corrections that preserve compatibility;
- minor: new backward-compatible capability or platform;
- major: incompatible behavior, structure, or requirements.

Run `prepare` to create platform packages, `release-manifest.json`,
`SHA256SUMS`, and release notes under `dist/<version>/`.

Before any GitHub mutation, show:

- source diff;
- validation result;
- proposed version;
- change summary;
- generated package names and SHA-256 values.

## Draft

Resolve GitHub CLI from `GH_CLI_PATH` first, then from `PATH`. Authentication
must already be configured through GitHub CLI.

Draft creation requires GitHub CLI authentication and this exact token:

```text
draft:<skill-id>@<version>
```

The Draft Release is not installable. Creating it does not authorize publication.

## Publish

Inspect the existing Draft Release and its assets. Show the final release summary
and request explicit approval.

Publishing requires:

```text
publish:<skill-id>@<version>
```

Only after receiving that approval may the Agent change the Draft to a stable
Release. Do not publish a prerelease, silently replace an existing asset, or move an
existing stable tag.

## Catalog

After a stable Release is published, update the public catalog only when repository
coordinates, visibility, supported Agents, or lifecycle status changed. The catalog
does not duplicate the latest version; update checks query stable Releases directly.

