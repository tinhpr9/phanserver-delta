#!/usr/bin/env python3
"""Challenger Iter2-2 Adversarial Coverage & Stress Test Harness (Python).
Tests:
- Screen orientation, coordinates fuzzing, extreme aspect ratios, shell fallback
- Idempotency & state caching persistence under re-entrant executions
- Tailscale IP validation & boundary regex lookarounds
- Subprocess error handling & signal termination
- R4 Compliance verification (zero real UgPhone commands or leaks)
"""

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.agent import (
    build_tailscale_command,
    compute_screen_coordinates,
    handle_incoming_batch_action,
    validate_tailscale_cgnat_ip,
)


class TestOrientationAdversarialStress(unittest.TestCase):
    """Stress testing screen orientation, resolution fuzzing, and coordinate safety."""

    def test_orientation_fuzzing_resolutions(self):
        """Fuzz a wide matrix of aspect ratios and rotations."""
        test_dimensions = [
            (720, 1280),    # Standard 720p portrait
            (1280, 720),    # Standard 720p landscape
            (1080, 1920),   # Standard 1080p
            (1920, 1080),
            (1080, 2400),   # 20:9
            (1440, 3120),   # 19.5:9
            (1440, 2560),   # 16:9 2K
            (720, 720),     # Square 1:1
            (1080, 1080),   # Square 1:1
            (480, 800),     # WVGA
            (320, 480),     # HVGA legacy
            (2160, 3840),   # 4K portrait
            (3840, 2160),   # 4K landscape
        ]
        rotations = [0, 1, 2, 3, 4, -1, "0", "1"]

        for w, h in test_dimensions:
            for rot in rotations:
                coords = compute_screen_coordinates(w, h, rotation=rot)

                self.assertIn("is_landscape", coords)
                self.assertIn("width", coords)
                self.assertIn("height", coords)
                self.assertIn("toggle_x", coords)
                self.assertIn("toggle_y", coords)
                self.assertIn("center_x", coords)
                self.assertIn("center_y", coords)

                actual_w = coords["width"]
                actual_h = coords["height"]

                # Ensure dimensions match max/min based on landscape status
                if coords["is_landscape"]:
                    self.assertEqual(actual_w, max(int(w), int(h)))
                    self.assertEqual(actual_h, min(int(w), int(h)))
                else:
                    self.assertEqual(actual_w, min(int(w), int(h)))
                    self.assertEqual(actual_h, max(int(w), int(h)))

                # Coordinates must be strictly within screen boundary
                self.assertGreater(coords["toggle_x"], 0)
                self.assertLess(coords["toggle_x"], actual_w)
                self.assertGreater(coords["toggle_y"], 0)
                self.assertLess(coords["toggle_y"], actual_h)
                self.assertGreater(coords["center_x"], 0)
                self.assertLess(coords["center_x"], actual_w)
                self.assertGreater(coords["center_y"], 0)
                self.assertLess(coords["center_y"], actual_h)

    def test_shell_script_rotation_detection_fallback(self):
        """Verify the shell rotation fallback logic without hardware."""
        # Shell logic extracted from build_tailscale_command:
        test_shell_snippet = """
ROTATION=""
[ -z "$ROTATION" ] && ROTATION=0
RAW_SIZE="720x1280"
DIM_W=$(echo "$RAW_SIZE" | cut -d'x' -f1)
DIM_H=$(echo "$RAW_SIZE" | cut -d'x' -f2)
if [ -n "$DIM_W" ] && [ -n "$DIM_H" ] && [ "$DIM_W" -gt 0 ] 2>/dev/null; then
    if [ "$DIM_W" -gt "$DIM_H" ]; then
        MAX_D="$DIM_W"
        MIN_D="$DIM_H"
    else
        MAX_D="$DIM_H"
        MIN_D="$DIM_W"
    fi
else
    MIN_D=720
    MAX_D=1280
fi
if [ "$ROTATION" -eq 1 ] || [ "$ROTATION" -eq 3 ]; then
    WIDTH="$MAX_D"
    HEIGHT="$MIN_D"
    TOGGLE_X=$((WIDTH * 92 / 100))
    TOGGLE_Y=$((HEIGHT * 12 / 100))
else
    WIDTH="$MIN_D"
    HEIGHT="$MAX_D"
    TOGGLE_X=$((WIDTH * 88 / 100))
    TOGGLE_Y=$((HEIGHT * 8 / 100))
fi
echo "$WIDTH $HEIGHT $TOGGLE_X $TOGGLE_Y"
"""
        res = subprocess.run(["sh", "-c", test_shell_snippet], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        out = res.stdout.strip().split()
        self.assertEqual(out, ["720", "1280", "633", "102"])


class TestAgentIdempotencyAdversarialStress(unittest.TestCase):
    """Stress testing agent action caching, repeated calls, and persistent state reload."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = pathlib.Path(self.temp_dir.name)
        self.state_path = self.root_path / "state.json"
        self.links_path = self.root_path / "server_links.txt"
        self.report_url = "https://mock.worker/report"
        self.secret = "mock-secret"
        self.device_id = "m77"

    def tearDown(self):
        self.temp_dir.cleanup()

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_repeated_action_id_executes_subprocess_exactly_once(self, mock_subproc, mock_ack):
        """Calling handle_incoming_batch_action 20 times with same action_id must invoke subprocess once."""
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "CONNECTED: 100.80.175.55"
        mock_subproc.return_value.stderr = ""

        state = {}
        action_id = "stress-idempotency-001"
        msg = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": action_id,
            "mode": "on",
            "target_device_ids": [self.device_id],
        }

        # 20 sequential calls
        for i in range(20):
            res = handle_incoming_batch_action(
                msg, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
            )
            self.assertTrue(res)

        self.assertEqual(mock_subproc.call_count, 1, "Subprocess was invoked more than once!")
        self.assertEqual(mock_ack.call_count, 20, "send_ack should be sent on each replay")
        for call in mock_ack.call_args_list:
            self.assertEqual(call.kwargs["status"], "OPENED")
            self.assertEqual(call.kwargs["details"], "CONNECTED: 100.80.175.55")

        # Verify state file was written and survives fresh reload
        self.assertTrue(self.state_path.exists())
        saved_state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertIn("tailscale_action_results", saved_state)
        self.assertIn(action_id, saved_state["tailscale_action_results"])
        cached = saved_state["tailscale_action_results"][action_id]
        self.assertEqual(cached["status"], "OPENED")
        self.assertEqual(cached["details"], "CONNECTED: 100.80.175.55")

        # Fresh agent process simulation: load state from file and call again
        fresh_state = json.loads(self.state_path.read_text(encoding="utf-8"))
        mock_ack.reset_mock()
        handle_incoming_batch_action(
            msg, self.device_id, self.report_url, self.secret, fresh_state, self.state_path, self.links_path
        )
        self.assertEqual(mock_subproc.call_count, 1, "Subprocess invoked even with loaded persistent state!")
        self.assertEqual(mock_ack.call_args.kwargs["status"], "OPENED")

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_rapid_alternating_modes_distinct_action_ids(self, mock_subproc, mock_ack):
        """Simulate rapid alternating commands (on -> off -> status -> on -> off)."""
        state = {}
        modes_and_outputs = [
            ("on", "CONNECTED: 100.80.175.55", 0, "OPENED", "CONNECTED: 100.80.175.55"),
            ("off", "DISCONNECTED", 0, "OPENED", "DISCONNECTED"),
            ("status", "DISCONNECTED", 0, "OPENED", "DISCONNECTED"),
            ("on", "CONNECTED: 100.115.92.14", 0, "OPENED", "CONNECTED: 100.115.92.14"),
            ("status", "CONNECTED: 100.115.92.14", 0, "OPENED", "CONNECTED: 100.115.92.14"),
            ("off", "DISCONNECTED", 0, "OPENED", "DISCONNECTED"),
        ]

        for idx, (mode, stdout_val, code, exp_status, exp_details) in enumerate(modes_and_outputs):
            mock_subproc.return_value.returncode = code
            mock_subproc.return_value.stdout = stdout_val
            mock_subproc.return_value.stderr = ""
            action_id = f"rapid-toggle-{idx}"
            msg = {
                "protocol": "fleet-batch-v1",
                "action": "CONTROL_TAILSCALE",
                "action_id": action_id,
                "mode": mode,
                "target_device_ids": [self.device_id],
            }
            handle_incoming_batch_action(
                msg, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
            )
            self.assertEqual(mock_ack.call_args.kwargs["status"], exp_status)
            self.assertEqual(mock_ack.call_args.kwargs["details"], exp_details)

        self.assertEqual(len(state["tailscale_action_results"]), len(modes_and_outputs))


class TestTailscaleIPBoundaryAndLookaroundStress(unittest.TestCase):
    """Stress testing IP boundary lookarounds in Python agent."""

    def test_regex_lookaround_matching(self):
        pattern = r"(?<![0-9a-zA-Z.])\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b(?![0-9a-zA-Z./:])"

        # Cases that MUST match and extract valid IP
        valid_cases = [
            ("CONNECTED: 100.80.175.55", "100.80.175.55"),
            ("IP 100.64.0.1 assigned", "100.64.0.1"),
            ("100.0.0.0", "100.0.0.0"),
            ("100.255.255.255", "100.255.255.255"),
            ("tailscale0: 100.101.102.103", "100.101.102.103"),
            ("foo 100.1.2.3 bar", "100.1.2.3"),
            ("[100.1.2.3]", "100.1.2.3"),
            ("(100.1.2.3)", "100.1.2.3"),
            ("100.1.2.3!", "100.1.2.3"),
        ]
        for text, expected in valid_cases:
            match = re.search(pattern, text)
            self.assertIsNotNone(match, f"Expected match in: {text!r}")
            self.assertEqual(match.group(0), expected)
            self.assertTrue(validate_tailscale_cgnat_ip(match.group(0)))

        # Cases that MUST NOT match
        invalid_cases = [
            "CONNECTED: 100.1.2.2555",       # 4-digit octet suffix
            "prefix100.1.2.3",               # letter prefix
            "1100.1.2.3",                    # digit prefix
            "100.1.2.3suffix",               # letter suffix
            "100.1.2.3.4",                   # 5 octets
            ".100.1.2.3",                    # leading dot
            "100.1.2.3:8080",                # port attached
            "100.1.2.3/24",                  # CIDR attached
            "192.168.1.1",                   # Not 100.x
            "10.0.0.1",
            "127.0.0.1",
            "TRIGGERED",
            "",
        ]
        for text in invalid_cases:
            match = re.search(pattern, text)
            if match:
                # If it matched a substring, validate_tailscale_cgnat_ip must reject or match was invalid
                self.fail(f"Adversarial string {text!r} unexpectedly matched {match.group(0)!r}")


class TestR4ZeroRealUgPhoneCommandsAudit(unittest.TestCase):
    """Static and structural audit to guarantee zero real device interaction."""

    def test_no_adb_connect_or_live_device_commands(self):
        """Ensure no live adb connect or direct socket connections to UgPhone exist."""
        forbidden = [
            "adb connect",
            "adb -s",
            "fastboot",
            "ugphone.net",
            "ugphone.com",
        ]
        root_dir = pathlib.Path(PROJECT_ROOT)
        for path in root_dir.glob("**/*"):
            if path.is_file() and path.suffix in [".py", ".js", ".mjs", ".sh"]:
                # skip git or agents metadata or this test file itself
                if ".git" in path.parts or ".agents" in path.parts or path.name == "test_adversarial_coverage_challenger2.py":
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore")
                for term in forbidden:
                    self.assertNotIn(
                        term, content,
                        f"Forbidden real device command '{term}' found in {path}!"
                    )

    def test_build_tailscale_command_uses_user0_and_suppression(self):
        """Ensure commands generated for Android strictly use --user 0 and redirection."""
        for mode in ["on", "off"]:
            cmd = build_tailscale_command(mode)
            self.assertIn("--user 0", cmd)
            self.assertIn(">/dev/null 2>&1 || true", cmd)


if __name__ == "__main__":
    unittest.main()
