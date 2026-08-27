#!/bin/bash
set -euo pipefail

echo "========================================="
echo "  RUNNING PHANSERVER-DELTA TEST SUITE"
echo "========================================="

echo "[1/12] Running test_tong_hop_link.mjs..."
node tests/test_tong_hop_link.mjs

echo "[2/12] Running test_telegram_phanserver.mjs..."
node tests/test_telegram_phanserver.mjs

echo "[3/12] Running test_fleet_state_2pc.mjs..."
node tests/test_fleet_state_2pc.mjs

echo "[4/12] Running test_pairing.mjs..."
node tests/test_pairing.mjs

echo "[5/12] Running test_worker_security.mjs..."
node tests/test_worker_security.mjs

echo "[6/12] Running test_credential_rotation.mjs..."
node tests/test_credential_rotation.mjs

echo "[7/12] Running test_legacy_credential_rotation.mjs..."
node tests/test_legacy_credential_rotation.mjs

echo "[8/12] Running test_hibernation_transport.mjs..."
node tests/test_hibernation_transport.mjs

echo "[9/12] Running delta updater tests..."
python3 -m unittest discover -s delta/tests

echo "[10/12] Running device agent tests..."
python3 -m unittest discover -s agent/tests

echo "[11/12] Running onboarding installer tests..."
python3 tests/test_onboarding_install.py

echo "[12/12] Running E2E flow tests..."
python3 tests/test_e2e_flow.py

echo "========================================="
echo "  ALL PHANSERVER-DELTA TESTS PASSED!"
echo "========================================="
