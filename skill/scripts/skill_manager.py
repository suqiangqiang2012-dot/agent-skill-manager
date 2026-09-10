#!/usr/bin/env python3
"""Check, install, and roll back stable Agent Skill releases."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile


STATE_SCHEMA = 1
CATALOG_SCHEMA = 1
MANIFEST_SCHEMA = 1
USER_AGENT = "agent-skill-manager/0.1"
SUPPORTED_INSTALL_AGENTS = {"codex"}


class ManagerError(RuntimeError):
    pass


class ConfirmationRequired(ManagerError):
    def __init__(self, message: str, payload: dict):
        super().__init__(message)
        self.payload = payload


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def state_home() -> Path:
    configured = os.environ.get("AGENT_SKILL_MANAGER_HOME")
    return Path(configured).expanduser().resolve() if configured else Path.home() / ".agent-skill-manager"


def load_json_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManagerError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManagerError(f"Invalid JSON in {path}: {exc}") from exc


def save_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def gh_executable() -> str | None:
    configured = os.environ.get("GH_CLI_PATH")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise ManagerError(f"GH_CLI_PATH does not exist: {path}")
        return str(path)
    return shutil.which("gh")


def github_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token.strip()
    gh = gh_executable()
    if not gh:
        return None
    result = subprocess.run(
        [gh, "auth", "token"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip() if result.returncode == 0 else None


def request_headers(token: str | None, accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def read_url_bytes(url: str, token: str | None, accept: str = "application/octet-stream") -> bytes:
    request = urllib.request.Request(url, headers=request_headers(token, accept))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise ManagerError(f"HTTP {exc.code} while reading {url}") from exc
    except urllib.error.URLError as exc:
        raise ManagerError(f"Cannot read {url}: {exc.reason}") from exc


def read_json_source(source: str, token: str | None = None) -> dict:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in {"http", "https"}:
        try:
            return json.loads(read_url_bytes(source, token, "application/json"))
        except json.JSONDecodeError as exc:
            raise ManagerError(f"Invalid JSON from {source}: {exc}") from exc
    return load_json_file(Path(source).expanduser().resolve())


def load_catalog(source: str) -> dict:
    catalog = read_json_source(source, github_token())
    if catalog.get("schema_version") != CATALOG_SCHEMA:
        raise ManagerError("Unsupported catalog schema")
    skills = catalog.get("skills")
    if not isinstance(skills, list):
        raise ManagerError("Catalog skills must be a list")
    seen: set[str] = set()
    for entry in skills:
        skill_id = entry.get("id")
        if not isinstance(skill_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill_id):
            raise ManagerError(f"Invalid skill id: {skill_id!r}")
        if skill_id in seen:
            raise ManagerError(f"Duplicate catalog skill: {skill_id}")
        seen.add(skill_id)
    return catalog


def load_state() -> dict:
    path = state_home() / "state.json"
    if not path.exists():
        return {"schema_version": STATE_SCHEMA, "installed": {}, "backups": {}}
    state = load_json_file(path)
    if state.get("schema_version") != STATE_SCHEMA:
        raise ManagerError("Unsupported local state schema")
    state.setdefault("installed", {})
    state.setdefault("backups", {})
    return state


def save_state(state: dict) -> None:
    save_json_atomic(state_home() / "state.json", state)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_digest(root: Path) -> str:
    if not root.is_dir():
        raise ManagerError(f"Skill directory not found: {root}")
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def normalize_version(value: str) -> str:
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value.strip())
    if not match:
        raise ManagerError(f"Stable semantic version required, got {value!r}")
    return ".".join(match.groups())


def version_tuple(value: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in normalize_version(value).split("."))  # type: ignore[return-value]


def runtime_target() -> tuple[str, str]:
    system = platform.system().lower()
    os_name = {"windows": "windows", "darwin": "macos"}.get(system, system)
    machine = platform.machine().lower()
    architecture = {
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
    }.get(machine, machine)
    return os_name, architecture


def find_catalog_entry(catalog: dict, skill_id: str) -> dict:
    for entry in catalog["skills"]:
        if entry["id"] == skill_id:
            return entry
    raise ManagerError(f"Skill not found in catalog: {skill_id}")


def latest_release(repository: str, token: str | None) -> dict:
    url = f"https://api.github.com/repos/{repository}/releases/latest"
    release = read_json_source(url, token)
    if release.get("draft") or release.get("prerelease"):
        raise ManagerError(f"Latest release for {repository} is not stable")
    normalize_version(str(release.get("tag_name", "")))
    return release


def release_asset(release: dict, name: str) -> dict:
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            return asset
    raise ManagerError(f"Release asset not found: {name}")


def download_asset(asset: dict, destination: Path, token: str | None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if token and asset.get("url"):
        data = read_url_bytes(asset["url"], token, "application/octet-stream")
    else:
        url = asset.get("browser_download_url")
        if not url:
            raise ManagerError(f"Asset has no download URL: {asset.get('name')}")
        data = read_url_bytes(url, None)
    destination.write_bytes(data)


def release_context(entry: dict, agent: str) -> tuple[dict, dict, dict, str | None]:
    repository = entry.get("repository")
    if not repository:
        raise ManagerError("Repository is not configured")
    token = github_token()
    if entry.get("visibility") == "private" and not token:
        raise ManagerError("Private repository requires GitHub CLI authentication")
    release = latest_release(repository, token)
    manifest_name = entry.get("release_manifest_asset", "release-manifest.json")
    manifest_asset = release_asset(release, manifest_name)
    with tempfile.TemporaryDirectory(prefix="agent-skill-manifest-") as temporary:
        manifest_path = Path(temporary) / manifest_name
        download_asset(manifest_asset, manifest_path, token)
        manifest_digest = str(manifest_asset.get("digest") or "")
        if manifest_digest.startswith("sha256:"):
            expected = manifest_digest.split(":", 1)[1].lower()
            if sha256_file(manifest_path).lower() != expected:
                raise ManagerError("Release manifest does not match GitHub asset digest")
        manifest = load_json_file(manifest_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ManagerError("Unsupported release manifest schema")
    if manifest.get("skill_id") != entry["id"]:
        raise ManagerError("Release manifest skill id does not match catalog")
    release_version = normalize_version(str(release["tag_name"]))
    if normalize_version(str(manifest.get("version", ""))) != release_version:
        raise ManagerError("Release tag and manifest version do not match")
    package = select_package(manifest, agent)
    return release, manifest, package, token


def select_package(manifest: dict, agent: str) -> dict:
    if agent not in SUPPORTED_INSTALL_AGENTS:
        raise ManagerError(f"Unsupported adapter: {agent}")
    os_name, architecture = runtime_target()
    candidates: list[tuple[int, dict]] = []
    for package in manifest.get("packages", []):
        if package.get("agent") != agent:
            continue
        systems = package.get("operating_systems", [])
        architectures = package.get("architectures", [])
        if os_name not in systems:
            continue
        if architecture not in architectures and "any" not in architectures:
            continue
        score = 2 if architecture in architectures else 1
        candidates.append((score, package))
    if not candidates:
        raise ManagerError(
            f"No compatible package for agent={agent}, os={os_name}, arch={architecture}"
        )
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def resolve_install_root(agent: str, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    if agent == "codex":
        codex_home = os.environ.get("CODEX_HOME")
        return (Path(codex_home).expanduser() if codex_home else Path.home() / ".codex") / "skills"
    raise ManagerError(f"Install root requires an implemented adapter: {agent}")


def check_requirements(package: dict) -> None:
    missing: list[str] = []
    unresolved: list[str] = []
    for requirement in package.get("requirements", []):
        if isinstance(requirement, str):
            if not shutil.which(requirement):
                missing.append(requirement)
            continue
        if not isinstance(requirement, dict):
            raise ManagerError("Invalid package requirement")
        kind = requirement.get("type")
        name = str(requirement.get("name", "unnamed"))
        if kind == "executable":
            if not shutil.which(name):
                missing.append(name)
        elif kind == "capability":
            unresolved.append(name)
        else:
            raise ManagerError(f"Unsupported requirement type: {kind}")
    if missing:
        raise ManagerError("Missing required executables: " + ", ".join(missing))
    if unresolved:
        raise ManagerError(
            "Human verification required for capabilities: " + ", ".join(unresolved)
        )


def validate_skill_directory(root: Path, expected_id: str) -> None:
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        raise ManagerError("Package does not contain SKILL.md")
    content = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.DOTALL)
    if not match:
        raise ManagerError("SKILL.md has invalid frontmatter")
    name_match = re.search(r"^name:\s*[\"']?([^\"'\r\n]+)", match.group(1), re.MULTILINE)
    if not name_match or name_match.group(1).strip() != expected_id:
        raise ManagerError("SKILL.md name does not match package skill id")


def safe_extract(package_path: Path, destination: Path) -> Path:
    with zipfile.ZipFile(package_path) as archive:
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ManagerError(f"Unsafe ZIP path: {info.filename}")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ManagerError(f"Symbolic links are not allowed: {info.filename}")
        archive.extractall(destination)
    if (destination / "SKILL.md").is_file():
        return destination
    children = [path for path in destination.iterdir() if path.is_dir()]
    candidates = [path for path in children if (path / "SKILL.md").is_file()]
    if len(candidates) != 1:
        raise ManagerError("Package must contain exactly one skill root")
    return candidates[0]


def backup_name(version: str) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    return f"{version}__{stamp}"


def install_skill(args: argparse.Namespace) -> dict:
    catalog = load_catalog(args.catalog)
    entry = find_catalog_entry(catalog, args.skill_id)
    release, manifest, package, token = release_context(entry, args.agent)
    version = normalize_version(str(manifest["version"]))
    required_confirmation = f"{args.skill_id}@{version}"
    proposal = {
        "action": "install",
        "skill_id": args.skill_id,
        "version": version,
        "summary": manifest.get("summary", ""),
        "package": package.get("asset"),
        "sha256": package.get("sha256"),
        "required_confirmation": required_confirmation,
    }
    if args.confirm != required_confirmation:
        raise ConfirmationRequired("Installation confirmation required", proposal)
    check_requirements(package)
    install_root = resolve_install_root(args.agent, args.install_root)
    install_root.mkdir(parents=True, exist_ok=True)
    target = install_root / args.skill_id
    state = load_state()
    installed = state["installed"].get(args.skill_id)
    if target.exists():
        current_digest = tree_digest(target)
        recorded_digest = installed.get("tree_sha256") if installed else None
        if current_digest != recorded_digest:
            overwrite_value = current_digest[:12]
            if args.overwrite_modified != overwrite_value:
                raise ConfirmationRequired(
                    "Installed skill has local modifications",
                    {
                        **proposal,
                        "local_tree_sha256": current_digest,
                        "required_overwrite_value": overwrite_value,
                    },
                )
    asset = release_asset(release, package["asset"])
    with tempfile.TemporaryDirectory(prefix=f"{args.skill_id}-") as temporary:
        temporary_path = Path(temporary)
        archive_path = temporary_path / package["asset"]
        download_asset(asset, archive_path, token)
        actual_sha = sha256_file(archive_path)
        expected_sha = str(package.get("sha256", "")).lower()
        if actual_sha.lower() != expected_sha:
            raise ManagerError("Package SHA-256 does not match release manifest")
        api_digest = str(asset.get("digest") or "")
        if api_digest.startswith("sha256:") and api_digest.split(":", 1)[1].lower() != actual_sha:
            raise ManagerError("Package SHA-256 does not match GitHub asset digest")
        extracted = temporary_path / "extracted"
        extracted.mkdir()
        source = safe_extract(archive_path, extracted)
        validate_skill_directory(source, args.skill_id)
        stage = install_root / f".{args.skill_id}.stage-{uuid.uuid4().hex}"
        shutil.copytree(source, stage)
        new_digest = tree_digest(stage)
        old = install_root / f".{args.skill_id}.old-{uuid.uuid4().hex}"
        backup_record = None
        try:
            if target.exists():
                os.replace(target, old)
            os.replace(stage, target)
            if old.exists():
                previous_version = installed.get("version", "unmanaged") if installed else "unmanaged"
                destination = state_home() / "backups" / args.skill_id / backup_name(previous_version)
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(old, destination)
                backup_record = {
                    "version": previous_version,
                    "path": str(destination),
                    "created_at": utc_now(),
                    "tree_sha256": tree_digest(destination),
                }
        except Exception:
            if not target.exists() and old.exists():
                os.replace(old, target)
            raise
    if backup_record:
        state["backups"].setdefault(args.skill_id, []).append(backup_record)
    state["installed"][args.skill_id] = {
        "version": version,
        "agent": args.agent,
        "install_root": str(install_root),
        "installed_at": utc_now(),
        "tree_sha256": new_digest,
        "release_tag": release["tag_name"],
    }
    save_state(state)
    return {**proposal, "status": "installed", "tree_sha256": new_digest}


def list_backups(skill_id: str) -> dict:
    state = load_state()
    backups = state["backups"].get(skill_id, [])
    return {"skill_id": skill_id, "backups": backups}


def rollback_skill(args: argparse.Namespace) -> dict:
    state = load_state()
    installed = state["installed"].get(args.skill_id)
    if not installed:
        raise ManagerError(f"Skill is not managed: {args.skill_id}")
    matches = [
        item
        for item in state["backups"].get(args.skill_id, [])
        if item.get("version") == args.version
    ]
    if not matches:
        raise ManagerError(f"Backup not found: {args.skill_id}@{args.version}")
    backup = matches[-1]
    backup_path = Path(backup["path"])
    if not backup_path.is_dir() or tree_digest(backup_path) != backup.get("tree_sha256"):
        raise ManagerError("Backup is missing or has been modified")
    confirmation = f"rollback:{args.skill_id}@{args.version}"
    proposal = {
        "action": "rollback",
        "skill_id": args.skill_id,
        "current_version": installed["version"],
        "target_version": args.version,
        "required_confirmation": confirmation,
    }
    if args.confirm != confirmation:
        raise ConfirmationRequired("Rollback confirmation required", proposal)
    install_root = Path(installed["install_root"])
    target = install_root / args.skill_id
    if not target.is_dir():
        raise ManagerError(f"Installed skill directory is missing: {target}")
    current_digest = tree_digest(target)
    if current_digest != installed.get("tree_sha256"):
        raise ManagerError("Installed skill has local modifications; rollback refused")
    stage = install_root / f".{args.skill_id}.rollback-{uuid.uuid4().hex}"
    current_old = install_root / f".{args.skill_id}.old-{uuid.uuid4().hex}"
    shutil.copytree(backup_path, stage)
    try:
        os.replace(target, current_old)
        os.replace(stage, target)
        current_backup = state_home() / "backups" / args.skill_id / backup_name(installed["version"])
        os.replace(current_old, current_backup)
    except Exception:
        if not target.exists() and current_old.exists():
            os.replace(current_old, target)
        raise
    state["backups"][args.skill_id].append(
        {
            "version": installed["version"],
            "path": str(current_backup),
            "created_at": utc_now(),
            "tree_sha256": tree_digest(current_backup),
        }
    )
    state["installed"][args.skill_id] = {
        **installed,
        "version": args.version,
        "installed_at": utc_now(),
        "tree_sha256": tree_digest(target),
        "release_tag": f"rollback:{args.version}",
    }
    save_state(state)
    return {**proposal, "status": "rolled-back"}


def check_updates(args: argparse.Namespace) -> dict:
    catalog = load_catalog(args.catalog)
    state = load_state()
    rows = []
    for entry in catalog["skills"]:
        installed = state["installed"].get(entry["id"])
        current = installed.get("version") if installed else None
        row = {
            "skill_id": entry["id"],
            "display_name": entry.get("display_name", entry["id"]),
            "current_version": current,
            "latest_version": None,
            "status": entry.get("status", "active"),
            "summary": "",
        }
        if entry.get("status") != "active":
            rows.append(row)
            continue
        if not entry.get("repository"):
            rows.append(row)
            continue
        if args.agent not in entry.get("supported_agents", []):
            row["status"] = "unsupported-agent"
            rows.append(row)
            continue
        try:
            _, manifest, _, _ = release_context(entry, args.agent)
            latest = normalize_version(str(manifest["version"]))
            row["latest_version"] = latest
            row["summary"] = manifest.get("summary", "")
            if current is None:
                row["status"] = "not-installed"
            elif version_tuple(latest) > version_tuple(current):
                row["status"] = "update-available"
            else:
                row["status"] = "current"
        except ManagerError as exc:
            row["status"] = "error"
            row["error"] = str(exc)
        rows.append(row)
    report = {"checked_at": utc_now(), "agent": args.agent, "skills": rows}
    if args.cache_report:
        save_json_atomic(state_home() / "last-check.json", report)
    return report


def print_result(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Check stable releases")
    check.add_argument("--catalog", required=True)
    check.add_argument("--agent", required=True)
    check.add_argument("--cache-report", action="store_true")

    install = subparsers.add_parser("install", help="Install one stable skill release")
    install.add_argument("skill_id")
    install.add_argument("--catalog", required=True)
    install.add_argument("--agent", required=True)
    install.add_argument("--install-root")
    install.add_argument("--confirm")
    install.add_argument("--overwrite-modified")

    backups = subparsers.add_parser("backups", help="List retained backups")
    backups.add_argument("skill_id")

    rollback = subparsers.add_parser("rollback", help="Restore a retained backup")
    rollback.add_argument("skill_id")
    rollback.add_argument("--version", required=True)
    rollback.add_argument("--confirm")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check":
            result = check_updates(args)
        elif args.command == "install":
            result = install_skill(args)
        elif args.command == "backups":
            result = list_backups(args.skill_id)
        elif args.command == "rollback":
            result = rollback_skill(args)
        else:
            raise ManagerError(f"Unknown command: {args.command}")
        print_result(result)
        return 0
    except ConfirmationRequired as exc:
        print_result({"status": "confirmation-required", "message": str(exc), **exc.payload})
        return 2
    except ManagerError as exc:
        print_result({"status": "error", "message": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())

