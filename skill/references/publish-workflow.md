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
Before requesting Draft authorization, revalidate the prepared release against the
current `skill/` source and `release.json`. Every declared Agent, operating system,
and architecture target must have exactly one matching package. Package files,
manifest metadata, and SHA-256 values must still match. Stop if the source or target
configuration changed after `prepare`.


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

After every stable Release publication, audit the public catalog:

- For a newly published skill, check whether its repository is registered. If it is
  missing, prepare a catalog entry for user review.
- For an already registered skill, do not update the catalog for a version-only
  release. Update it only when repository coordinates, visibility, supported Agents,
  or lifecycle status changed.
- Show the catalog diff and validation result before asking to commit. Catalog commit
  and push are separate actions and each requires explicit authorization.

The catalog does not duplicate the latest version; update checks query stable
Releases directly.

After the Release and any required catalog update are publicly available, run
read-only `check` commands for every supported Agent. Report whether each Agent can
discover the stable Release and whether a compatible package is available. These
checks do not authorize installation.

