import os
import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "deploy" / "install.sh"
SERVICE = ROOT / "deploy" / "device_service.sh"
AGENT = ROOT / "agent" / "agent.py"


class TestOnboardingInstaller(unittest.TestCase):
    def run_installer_test_mode(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PHANSERVER_INSTALL_TEST_MODE"] = "1"
        return subprocess.run(
            ["bash", str(INSTALLER), *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_shell_syntax(self):
        for path in (INSTALLER, SERVICE):
            result = subprocess.run(
                ["bash", "-n", str(path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_numeric_id_and_group_two_normalize_without_mutation(self):
        result = self.run_installer_test_mode("73", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PHANSERVER_DEVICE_ID=m73", result.stdout)
        self.assertIn("PHANSERVER_DEVICE_GROUP=NOVA", result.stdout)
        self.assertIn("PHANSERVER_SOURCE_REF=main", result.stdout)

    def test_prefixed_id_and_marmot_group_normalize_without_mutation(self):
        result = self.run_installer_test_mode("M74", "marmot")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PHANSERVER_DEVICE_ID=m74", result.stdout)
        self.assertIn("PHANSERVER_DEVICE_GROUP=MARMOT", result.stdout)

    def test_invalid_identity_fails_closed(self):
        for args in (("0", "2"), ("m0", "2"), ("73", "3"), ("abc", "NOVA")):
            result = self.run_installer_test_mode(*args)
            self.assertNotEqual(result.returncode, 0, (args, result.stdout, result.stderr))

    def test_missing_args_fails_closed(self):
        result = self.run_installer_test_mode()
        self.assertNotEqual(result.returncode, 0)

    def test_source_contains_pinned_revision_and_pairing_flow(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("resolve_revision", source)
        self.assertIn('RELEASE_ROOT="$INSTALL_ROOT/releases"', source)
        self.assertIn('RELEASE_DIR="$RELEASE_ROOT/$REVISION"', source)
        self.assertIn("/agent/pair/request", source)
        self.assertIn("/agent/pair/status", source)
        self.assertIn("PHANSERVER_ONBOARDING=READY", source)

    def test_agent_has_no_m72_identity_fallback(self):
        source = AGENT.read_text(encoding="utf-8")
        self.assertNotIn('or "m72"', source)
        self.assertIn('raise RuntimeError("device_id_missing_or_invalid")', source)


if __name__ == "__main__":
    unittest.main()
