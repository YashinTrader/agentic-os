import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.check_cognee_profile import ProfileError, load_profile, validate_profile


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO_ROOT / "memory" / "cognee-local.env.example"


class CogneeLocalProfileTests(unittest.TestCase):
    def test_checked_in_profile_is_local_first(self) -> None:
        profile = load_profile(PROFILE_PATH)
        summary = validate_profile(profile)

        self.assertEqual(summary["llm_provider"], "ollama")
        self.assertEqual(summary["embedding_provider"], "fastembed")
        self.assertEqual(summary["graph_provider"], "kuzu")
        self.assertEqual(summary["vector_provider"], "lancedb")
        self.assertEqual(summary["db_provider"], "sqlite")
        self.assertFalse(summary["cloud_providers_enabled"])
        self.assertFalse(summary["ingestion_enabled"])

    def test_rejects_partial_local_configuration(self) -> None:
        profile = load_profile(PROFILE_PATH)
        profile["EMBEDDING_PROVIDER"] = "openai"

        with self.assertRaisesRegex(ProfileError, "EMBEDDING_PROVIDER"):
            validate_profile(profile)

    def test_rejects_cloud_provider_flag(self) -> None:
        profile = load_profile(PROFILE_PATH)
        profile["AGENTIC_OS_ENABLE_CLOUD_PROVIDERS"] = "true"

        with self.assertRaisesRegex(ProfileError, "cloud providers"):
            validate_profile(profile)

    def test_rejects_enabled_ingestion(self) -> None:
        profile = load_profile(PROFILE_PATH)
        profile["AGENTIC_OS_INGESTION_ENABLED"] = "true"

        with self.assertRaisesRegex(ProfileError, "ingestion"):
            validate_profile(profile)

    def test_script_validates_profile_without_optional_services(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "check_cognee_profile.py"), "--json"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["profile"], "local")
        self.assertEqual(payload["llm_model"], "llama3.1:8b")

    def test_script_reports_invalid_profile(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write('LLM_PROVIDER="ollama"\n')
            invalid_path = Path(handle.name)

        self.addCleanup(invalid_path.unlink)
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "check_cognee_profile.py"),
                "--profile",
                str(invalid_path),
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing required keys", result.stderr)

    def test_requirements_declares_cognee_dependency(self) -> None:
        requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()

        self.assertIn("cognee==1.1.0", requirements)


if __name__ == "__main__":
    unittest.main()
