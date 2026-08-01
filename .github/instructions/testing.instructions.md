---
applyTo: "**"
---

# Testing Instructions

Follow `AGENTS.md` § Software Engineering Foundation and `.cursor/rules/20-testing-and-tdd.mdc`.

## Expectations

- **Behavior first:** Tests validate what the code does, not implementation trivia.
- **Pyramid:** ~90% unit tests in `tests/` when possible.
- **Runner:** `pytest` or `npm run test:unit` (`pip install -e ".[dev]"` first).
- **Integration:** When behavior crosses helpers ↔ scripts ↔ config manifests.
- **E2E:** Sparingly — full setup smoke, critical install path only.

## By change type

| Change | Tests to add/update |
| ------ | ------------------- |
| New helper | Unit tests with fixtures/mocks at IO boundary |
| Config/manifest | Contract tests (`test_avo_config`, `test_validate_dependencies`) |
| Install scripts | `test_install_scripts`, dry-run checks |
| Gitignore/docs policy | `test_gitignore_scope`, `test_video_use_traces` |
| Editorial/video | QC checklists + review exports — not only unit tests |

## Do not

- Delete tests without equivalent coverage
- Change behavior without explicit user request
- Rely on E2E when a unit test suffices
