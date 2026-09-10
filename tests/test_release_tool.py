import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import release_tool  # noqa: E402


class ReleaseToolTests(unittest.TestCase):
    def create_repo(self, root: Path) -> Path:
        repo = root / "skill-example"
        skill = repo / "skill"
        references = skill / "references"
        references.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\n"
            "name: example-skill\n"
            "description: Handles example tasks when explicitly requested.\n"
            "---\n\n"
            "# Example\n\n"
            "Read [details](references/details.md).\n",
            encoding="utf-8",
        )
        (references / "details.md").write_text("# Details\n", encoding="utf-8")
        (repo / "release.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "skill_id": "example-skill",
                    "targets": [
                        {
                            "agent": "codex",
                            "operating_systems": ["windows", "macos"],
                            "architectures": ["any"],
                            "minimum_agent_version": None,
                            "install_mode": "copy",
                            "reload_required": True,
                            "requirements": [],
                        },
                        {
                            "agent": "workbuddy",
                            "operating_systems": ["windows"],
                            "architectures": ["any"],
                            "minimum_agent_version": "5.5.4",
                            "install_mode": "copy",
                            "reload_required": False,
                            "requirements": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return repo

    def test_validate_and_prepare(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.create_repo(Path(temporary))
            validation = release_tool.validate_skill(repo / "skill")
            self.assertEqual(validation["skill_id"], "example-skill")
            self.assertEqual(validation["file_count"], 2)

            result = release_tool.prepare_release(repo, "1.2.3", "Stable example.")
            self.assertEqual(result["status"], "prepared")
            manifest_path = repo / "dist" / "1.2.3" / "release-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            packages = {item["agent"]: item for item in manifest["packages"]}
            self.assertEqual(set(packages), {"codex", "workbuddy"})
            self.assertEqual(
                packages["workbuddy"]["minimum_agent_version"],
                "5.5.4",
            )
            self.assertFalse(packages["workbuddy"]["reload_required"])
            package = packages["workbuddy"]
            archive_path = manifest_path.parent / package["asset"]
            actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            self.assertEqual(actual, package["sha256"])
            self.assertEqual(
                packages["codex"]["sha256"],
                packages["workbuddy"]["sha256"],
            )
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    ["SKILL.md", "references/details.md"],
                )

    def test_invalid_minimum_agent_version_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.create_repo(Path(temporary))
            config_path = repo / "release.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["targets"][1]["minimum_agent_version"] = "5.5"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(release_tool.ReleaseError):
                release_tool.prepare_release(repo, "1.2.3", "Invalid target.")

    def test_missing_reference_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.create_repo(Path(temporary))
            (repo / "skill" / "references" / "details.md").unlink()
            with self.assertRaises(release_tool.ReleaseError):
                release_tool.validate_skill(repo / "skill")

    def test_draft_requires_exact_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.create_repo(Path(temporary))
            release_tool.prepare_release(repo, "1.0.0", "Initial stable release.")
            with self.assertRaises(release_tool.ConfirmationRequired) as context:
                release_tool.draft_release(repo, "owner/example-skill", "1.0.0", None)
            self.assertEqual(
                context.exception.payload["required_confirmation"],
                "draft:example-skill@1.0.0",
            )


if __name__ == "__main__":
    unittest.main()

