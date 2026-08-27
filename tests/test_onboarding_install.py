import os
import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
BOOTSTRAP = ROOT / "deploy" / "install.sh"
INSTALLER = ROOT / "deploy" / "install_runtime.sh"
SERVICE = ROOT / "deploy" / "device_service.sh"
AGENT = ROOT / "agent" / "agent.py"
SECURE_AGENT = ROOT / "agent" / "secure_agent.py"


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
        for path in (BOOTSTRAP, INSTALLER, SERVICE):
            result = subprocess.run(
                ["bash", "-n", str(path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, f"{path}: {result.stderr}")

    def test_python_runtime_syntax(self):
        result = subprocess.run(
            ["python3", "-m", "py_compile", str(AGENT), str(SECURE_AGENT)],
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

    def test_installer_pins_revision_pairs_and_verifies_own_device(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("resolve_revision", source)
        self.assertIn('RELEASE_ROOT="$INSTALL_ROOT/releases"', source)
        self.assertIn('RELEASE_DIR="$RELEASE_ROOT/$REVISION"', source)
        self.assertIn("/agent/pair/request", source)
        self.assertIn("/agent/pair/status", source)
        self.assertIn("/agent/status", source)
        self.assertNotIn("/aot/hub/state", source)
        self.assertIn("PHANSERVER_ONBOARDING=READY", source)

    def test_installer_uses_private_state_and_transactional_rollback(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('DEVICE_ROOT="$INSTALL_ROOT/device"', source)
        self.assertNotIn("/storage/emulated/0/Download/Shouko", source)
        self.assertIn("snapshot_file identity", source)
        self.assertIn("snapshot_file config", source)
        self.assertIn("snapshot_file service", source)
        self.assertIn("snapshot_file boot", source)
        self.assertIn("rollback_transaction", source)
        self.assertIn("PHANSERVER_ROLLBACK=RESTORED", source)

    def test_installed_service_uses_hardened_transport(self):
        service_source = SERVICE.read_text(encoding="utf-8")
        secure_source = SECURE_AGENT.read_text(encoding="utf-8")
        self.assertIn('AGENT="$ROOT/agent/secure_agent.py"', service_source)
        self.assertIn('f"X-Agent-Secret: {self.secret}\\r\\n"', secure_source)
        self.assertIn('urllib.parse.urlencode({"device_id": device_id, "group": device_group})', secure_source)
        self.assertNotIn('"secret": secret', secure_source)
        self.assertIn('device_root = state_root / "device"', secure_source)

    def test_agent_has_no_m72_identity_fallback(self):
        source = AGENT.read_text(encoding="utf-8")
        self.assertNotIn('or "m72"', source)
        self.assertIn('raise RuntimeError("device_id_missing_or_invalid")', source)


if __name__ == "__main__":
    unittest.main()
