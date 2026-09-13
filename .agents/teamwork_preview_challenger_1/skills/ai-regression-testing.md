# AI Regression Testing Skill Reference

Testing patterns specifically designed for AI-assisted development, where the same model writes code and reviews it — creating systematic blind spots that only automated tests can catch.

Key Principles:
1. Write tests for bugs that were found and edge cases, not just happy paths.
2. Adversarial test generators: stress test boundaries, bad inputs, failure modes.
3. Test where bugs cluster: multi-path logic, state transitions, parsing logic.
4. Independent verification: never trust claims without running empirical tests.
