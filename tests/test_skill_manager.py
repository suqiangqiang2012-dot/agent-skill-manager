import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import skill_manager  # noqa: E402


class SkillManagerTests(unittest.TestCase):
    def setUp(self):
        self.original_home = os.environ.get("AGENT_SKILL_MANAGER_HOME")

    def tearDown(self):
        if self.original_home is None:
            os.environ.pop("AGENT_SKILL_MANAGER_HOME", None)
        else:
            os.environ["AGENT_SKILL_MANAGER_HOME"] = self.original_home

    def test_semantic_versions(self):
        self.assertEqual(skill_manager.normalize_version("v1.2.3"), "1.2.3")
        self.assertGreater(
            skill_manager.version_tuple("2.0.0"),
            skill_manager.version_tuple("1.9.9"),
        )
        with self.assertRaises(skill_manager.ManagerError):
            skill_manager.normalize_version("1.2")

    def test_selects_universal_codex_package(self):
        os_name, _ = skill_manager.runtime_target()
        manifest = {
            "packages": [
                {
                    "agent": "codex",
                    "operating_systems": [os_name],
                    "architectures": ["any"],
                    "asset": "skill.zip",
                }
            ]
        }
        selected = skill_manager.select_package(manifest, "codex")
        self.assertEqual(selected["asset"], "skill.zip")

    def test_unsupported_adapter_fails(self):
        with self.assertRaises(skill_manager.ManagerError):
            skill_manager.select_package({"packages": []}, "workbuddy")

    def test_safe_extract_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../outside.txt", "unsafe")
            destination = root / "extract"
            destination.mkdir()
            with self.assertRaises(skill_manager.ManagerError):
                skill_manager.safe_extract(archive, destination)
            self.assertFalse((root / "outside.txt").exists())

    def test_check_keeps_unpublished_catalog_entry_visible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            os.environ["AGENT_SKILL_MANAGER_HOME"] = str(root / "state")
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "catalog_id": "test",
                        "skills": [
                            {
                                "id": "example-skill",
                                "display_name": "Example",
                                "description": "Example",
                                "visibility": "private",
                                "repository": "owner/not-published",
                                "release_manifest_asset": "release-manifest.json",
                                "supported_agents": ["codex"],
                                "status": "local-preparation",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                catalog=str(catalog),
                agent="codex",
                cache_report=True,
            )
            report = skill_manager.check_updates(args)
            self.assertEqual(report["skills"][0]["status"], "local-preparation")
            self.assertTrue((root / "state" / "last-check.json").is_file())

    def test_install_detects_changes_and_rollback_restores_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            os.environ["AGENT_SKILL_MANAGER_HOME"] = str(root / "state")
            install_root = root / "skills"
            catalog_path = root / "catalog.json"
            catalog_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "catalog_id": "test",
                        "skills": [
                            {
                                "id": "example-skill",
                                "display_name": "Example",
                                "description": "Example",
                                "visibility": "private",
                                "repository": "owner/example-skill",
                                "release_manifest_asset": "release-manifest.json",
                                "supported_agents": ["codex"],
                                "status": "active",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def create_archive(version):
                archive_path = root / f"example-{version}.zip"
                with zipfile.ZipFile(archive_path, "w") as archive:
                    archive.writestr(
                        "SKILL.md",
                        "---\nname: example-skill\n"
                        "description: Example skill.\n---\n\n"
                        f"# Version {version}\n",
                    )
                return archive_path

            def context_for(version, archive_path):
                package = {
                    "agent": "codex",
                    "operating_systems": [skill_manager.runtime_target()[0]],
                    "architectures": ["any"],
                    "requirements": [],
                    "asset": archive_path.name,
                    "sha256": skill_manager.sha256_file(archive_path),
                }
                release = {
                    "tag_name": f"v{version}",
                    "assets": [
                        {
                            "name": archive_path.name,
                            "digest": f"sha256:{package['sha256']}",
                        }
                    ],
                }
                manifest = {
                    "schema_version": 1,
                    "skill_id": "example-skill",
                    "version": version,
                    "summary": f"Version {version}",
                    "packages": [package],
                }
                return release, manifest, package, None

            def install_args(version, overwrite=None):
                return argparse.Namespace(
                    skill_id="example-skill",
                    catalog=str(catalog_path),
                    agent="codex",
                    install_root=str(install_root),
                    confirm=f"example-skill@{version}",
                    overwrite_modified=overwrite,
                )

            archive_v1 = create_archive("1.0.0")
            with mock.patch.object(
                skill_manager,
                "release_context",
                return_value=context_for("1.0.0", archive_v1),
            ), mock.patch.object(
                skill_manager,
                "download_asset",
                side_effect=lambda asset, destination, token: shutil.copy2(
                    archive_v1, destination
                ),
            ):
                result = skill_manager.install_skill(install_args("1.0.0"))
            self.assertEqual(result["status"], "installed")

            installed_file = install_root / "example-skill" / "SKILL.md"
            installed_file.write_text(
                installed_file.read_text(encoding="utf-8") + "\nlocal edit\n",
                encoding="utf-8",
            )
            archive_v2 = create_archive("1.1.0")
            with mock.patch.object(
                skill_manager,
                "release_context",
                return_value=context_for("1.1.0", archive_v2),
            ):
                with self.assertRaises(skill_manager.ConfirmationRequired) as context:
                    skill_manager.install_skill(install_args("1.1.0"))
            overwrite = context.exception.payload["required_overwrite_value"]

            with mock.patch.object(
                skill_manager,
                "release_context",
                return_value=context_for("1.1.0", archive_v2),
            ), mock.patch.object(
                skill_manager,
                "download_asset",
                side_effect=lambda asset, destination, token: shutil.copy2(
                    archive_v2, destination
                ),
            ):
                skill_manager.install_skill(install_args("1.1.0", overwrite))

            backups = skill_manager.list_backups("example-skill")["backups"]
            self.assertEqual(backups[-1]["version"], "1.0.0")
            rollback_args = argparse.Namespace(
                skill_id="example-skill",
                version="1.0.0",
                confirm="rollback:example-skill@1.0.0",
            )
            result = skill_manager.rollback_skill(rollback_args)
            self.assertEqual(result["status"], "rolled-back")
            self.assertIn("# Version 1.0.0", installed_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

