#!/usr/bin/env python3
"""Validate, package, draft, and publish one versioned Agent Skill."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import zipfile


ALLOWED_FRONTMATTER_KEYS = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
}
SUPPORTED_AGENTS = {
    "codex",
    "claude-code",
    "cursor",
    "openclaw",
    "workbuddy",
    "deepseek-harness",
}


class ReleaseError(RuntimeError):
    pass


class ConfirmationRequired(ReleaseError):
    def __init__(self, message: str, payload: dict):
        super().__init__(message)
        self.payload = payload


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def normalize_version(value: str) -> str:
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value.strip())
    if not match:
        raise ReleaseError(f"Stable semantic version required, got {value!r}")
    return ".".join(match.groups())


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"Invalid JSON in {path}: {exc}") from exc


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_json_atomic(path: Path, value: dict) -> None:
    write_text_atomic(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_files(skill_dir: Path) -> list[Path]:
    files = []
    for path in skill_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(skill_dir)
        if any(part in {".git", "__pycache__"} for part in relative.parts):
            continue
        if path.name in {".DS_Store"} or path.suffix in {".pyc", ".pyo"}:
            continue
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(skill_dir).as_posix())


def parse_frontmatter(skill_md: Path) -> dict[str, str]:
    content = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", content, re.DOTALL)
    if not match:
        raise ReleaseError("SKILL.md has invalid YAML frontmatter")
    values: dict[str, str] = {}
    keys: set[str] = set()
    for raw_line in match.group(1).splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line[:1].isspace():
            continue
        if ":" not in raw_line:
            raise ReleaseError(f"Invalid frontmatter line: {raw_line}")
        key, value = raw_line.split(":", 1)
        key = key.strip()
        keys.add(key)
        values[key] = value.strip().strip("'\"")
    unexpected = keys - ALLOWED_FRONTMATTER_KEYS
    if unexpected:
        raise ReleaseError(
            "Unsupported SKILL.md frontmatter keys: " + ", ".join(sorted(unexpected))
        )
    for required in ("name", "description"):
        if not values.get(required):
            raise ReleaseError(f"SKILL.md frontmatter is missing {required}")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", values["name"]):
        raise ReleaseError("SKILL.md name must use lowercase hyphen-case")
    if "[TODO:" in content:
        raise ReleaseError("SKILL.md contains an unfinished TODO placeholder")
    return values


def validate_local_links(skill_dir: Path, skill_md: Path) -> list[str]:
    content = skill_md.read_text(encoding="utf-8")
    missing: list[str] = []
    for raw_target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
        target = raw_target.strip().split("#", 1)[0]
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        decoded = PurePosixPath(target)
        if decoded.is_absolute() or ".." in decoded.parts:
            missing.append(f"unsafe:{raw_target}")
            continue
        if not (skill_dir / Path(*decoded.parts)).exists():
            missing.append(raw_target)
    return sorted(set(missing))


def validate_skill(skill_dir: Path) -> dict:
    skill_dir = skill_dir.resolve()
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise ReleaseError(f"SKILL.md not found in {skill_dir}")
    frontmatter = parse_frontmatter(skill_md)
    missing_links = validate_local_links(skill_dir, skill_md)
    if missing_links:
        raise ReleaseError("Missing or unsafe local references: " + ", ".join(missing_links))
    inventory = []
    for path in source_files(skill_dir):
        try:
            inventory.append(
                {
                    "path": path.relative_to(skill_dir).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        except OSError as exc:
            raise ReleaseError(f"Cannot read skill file {path}: {exc}") from exc
    if not inventory:
        raise ReleaseError("Skill directory is empty")
    return {
        "status": "valid",
        "skill_id": frontmatter["name"],
        "description": frontmatter["description"],
        "file_count": len(inventory),
        "files": inventory,
    }


def validate_release_config(config: dict, expected_skill_id: str) -> list[dict]:
    if config.get("schema_version") != 1:
        raise ReleaseError("Unsupported release.json schema")
    if config.get("skill_id") != expected_skill_id:
        raise ReleaseError("release.json skill_id does not match SKILL.md")
    targets = config.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ReleaseError("release.json must declare at least one target")
    seen: set[tuple] = set()
    for target in targets:
        agent = target.get("agent")
        if agent not in SUPPORTED_AGENTS:
            raise ReleaseError(f"Unsupported target agent: {agent}")
        systems = target.get("operating_systems")
        architectures = target.get("architectures")
        if not isinstance(systems, list) or not systems:
            raise ReleaseError(f"Target {agent} has no operating systems")
        if not isinstance(architectures, list) or not architectures:
            raise ReleaseError(f"Target {agent} has no architectures")
        key = (agent, tuple(sorted(systems)), tuple(sorted(architectures)))
        if key in seen:
            raise ReleaseError(f"Duplicate release target: {agent}")
        seen.add(key)
        if target.get("install_mode") != "copy":
            raise ReleaseError(f"Unsupported install mode for {agent}")
        requirements = target.get("requirements", [])
        if not isinstance(requirements, list):
            raise ReleaseError(f"Target {agent} requirements must be a list")
    return targets


def zip_label(target: dict) -> str:
    systems = target["operating_systems"]
    architectures = target["architectures"]
    if set(systems) == {"windows", "macos"} and architectures == ["any"]:
        return "any"
    os_label = "-".join(sorted(systems))
    arch_label = "-".join(sorted(architectures))
    return f"{os_label}-{arch_label}"


def add_file_deterministic(archive: zipfile.ZipFile, path: Path, relative: str) -> None:
    info = zipfile.ZipInfo(relative, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, path.read_bytes())


def package_skill(skill_dir: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w") as archive:
        for path in source_files(skill_dir):
            relative = path.relative_to(skill_dir).as_posix()
            add_file_deterministic(archive, path, relative)


def prepare_release(repo_dir: Path, version: str, summary: str) -> dict:
    repo_dir = repo_dir.resolve()
    version = normalize_version(version)
    skill_dir = repo_dir / "skill"
    validation = validate_skill(skill_dir)
    config = read_json(repo_dir / "release.json")
    targets = validate_release_config(config, validation["skill_id"])
    output = repo_dir / "dist" / version
    if output.exists() and any(output.iterdir()):
        raise ReleaseError(f"Release output already exists and is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    packages = []
    for target in targets:
        label = zip_label(target)
        asset_name = (
            f"{validation['skill_id']}-v{version}-{target['agent']}-{label}.zip"
        )
        asset_path = output / asset_name
        package_skill(skill_dir, asset_path)
        packages.append(
            {
                "agent": target["agent"],
                "operating_systems": target["operating_systems"],
                "architectures": target["architectures"],
                "minimum_agent_version": target.get("minimum_agent_version"),
                "install_mode": target["install_mode"],
                "reload_required": bool(target.get("reload_required", True)),
                "requirements": target.get("requirements", []),
                "asset": asset_name,
                "sha256": sha256_file(asset_path),
            }
        )
    manifest = {
        "schema_version": 1,
        "skill_id": validation["skill_id"],
        "version": version,
        "channel": "stable",
        "summary": summary.strip(),
        "generated_at": utc_now(),
        "source_file_count": validation["file_count"],
        "source_files": validation["files"],
        "packages": packages,
    }
    manifest_path = output / "release-manifest.json"
    write_json_atomic(manifest_path, manifest)
    checksum_lines = [f"{item['sha256']}  {item['asset']}" for item in packages]
    write_text_atomic(output / "SHA256SUMS", "\n".join(checksum_lines) + "\n")
    notes = [
        f"# {validation['skill_id']} v{version}",
        "",
        summary.strip(),
        "",
        "## Packages",
        "",
    ]
    for item in packages:
        notes.append(
            f"- `{item['asset']}` — {item['agent']}; "
            f"OS: {', '.join(item['operating_systems'])}; "
            f"arch: {', '.join(item['architectures'])}"
        )
    notes.extend(
        [
            "",
            "## Validation",
            "",
            f"- Structure: valid",
            f"- Source files: {validation['file_count']}",
            "- Package integrity: SHA-256 generated",
            "",
        ]
    )
    write_text_atomic(output / "release-notes.md", "\n".join(notes))
    return {
        "status": "prepared",
        "skill_id": validation["skill_id"],
        "version": version,
        "summary": summary.strip(),
        "output": str(output),
        "packages": packages,
    }


def require_gh() -> str:
    configured = os.environ.get("GH_CLI_PATH")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise ReleaseError(f"GH_CLI_PATH does not exist: {path}")
        gh = str(path)
    else:
        gh = shutil.which("gh")
    if gh is None:
        raise ReleaseError("GitHub CLI is required but was not found")
    result = subprocess.run(
        [gh, "auth", "status"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise ReleaseError("GitHub CLI is not authenticated")
    return gh


def run_gh(arguments: list[str], capture: bool = False) -> str:
    gh = require_gh()
    result = subprocess.run(
        [gh, *arguments],
        check=False,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "GitHub CLI command failed"
        raise ReleaseError(message)
    return result.stdout.strip() if capture else ""


def draft_release(repo_dir: Path, repository: str, version: str, confirm: str | None) -> dict:
    repo_dir = repo_dir.resolve()
    version = normalize_version(version)
    output = repo_dir / "dist" / version
    manifest = read_json(output / "release-manifest.json")
    skill_id = manifest.get("skill_id")
    token = f"draft:{skill_id}@{version}"
    proposal = {
        "action": "create-draft-release",
        "repository": repository,
        "skill_id": skill_id,
        "version": version,
        "summary": manifest.get("summary", ""),
        "required_confirmation": token,
    }
    if confirm != token:
        raise ConfirmationRequired("Draft Release confirmation required", proposal)
    assets = [
        str(path)
        for path in sorted(output.iterdir())
        if path.name != "release-notes.md" and path.is_file()
    ]
    run_gh(
        [
            "release",
            "create",
            f"v{version}",
            *assets,
            "--repo",
            repository,
            "--draft",
            "--title",
            f"{skill_id} v{version}",
            "--notes-file",
            str(output / "release-notes.md"),
        ]
    )
    return {**proposal, "status": "draft-created"}


def publish_release(repository: str, skill_id: str, version: str, confirm: str | None) -> dict:
    version = normalize_version(version)
    token = f"publish:{skill_id}@{version}"
    proposal = {
        "action": "publish-release",
        "repository": repository,
        "skill_id": skill_id,
        "version": version,
        "required_confirmation": token,
    }
    if confirm != token:
        raise ConfirmationRequired("Stable Release confirmation required", proposal)
    raw = run_gh(
        [
            "release",
            "view",
            f"v{version}",
            "--repo",
            repository,
            "--json",
            "isDraft,isPrerelease,tagName",
        ],
        capture=True,
    )
    release = json.loads(raw)
    if not release.get("isDraft") or release.get("isPrerelease"):
        raise ReleaseError("Release must be an existing non-prerelease Draft")
    run_gh(
        [
            "release",
            "edit",
            f"v{version}",
            "--repo",
            repository,
            "--draft=false",
            "--latest",
        ]
    )
    return {**proposal, "status": "published"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--skill-dir", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--repo-dir", required=True)
    prepare.add_argument("--version", required=True)
    prepare.add_argument("--summary", required=True)

    draft = subparsers.add_parser("draft")
    draft.add_argument("--repo-dir", required=True)
    draft.add_argument("--repository", required=True)
    draft.add_argument("--version", required=True)
    draft.add_argument("--confirm")

    publish = subparsers.add_parser("publish")
    publish.add_argument("--repository", required=True)
    publish.add_argument("--skill-id", required=True)
    publish.add_argument("--version", required=True)
    publish.add_argument("--confirm")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            result = validate_skill(Path(args.skill_dir))
        elif args.command == "prepare":
            result = prepare_release(Path(args.repo_dir), args.version, args.summary)
        elif args.command == "draft":
            result = draft_release(
                Path(args.repo_dir), args.repository, args.version, args.confirm
            )
        elif args.command == "publish":
            result = publish_release(
                args.repository, args.skill_id, args.version, args.confirm
            )
        else:
            raise ReleaseError(f"Unknown command: {args.command}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ConfirmationRequired as exc:
        print(
            json.dumps(
                {"status": "confirmation-required", "message": str(exc), **exc.payload},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    except (ReleaseError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())

