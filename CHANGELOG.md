# Changelog

All notable changes to the **AVO orchestrator** (this repository) will be documented in
this file.

This project follows [Semantic Versioning](https://semver.org/) for software releases.

Format: `MAJOR.MINOR.PATCH` · Git tags: `vMAJOR.MINOR.PATCH` (annotated).

> **Note:** Video **export** versions for footage projects use a separate immutable scheme
> (`YYYYMMDD-video-slug-stage-v001`) documented in `AGENTS.md` and `docs/versioning.md`.
> Do not confuse editorial export versions with orchestrator SemVer.

## [Unreleased]

### Added

- Software engineering foundation: agent rules, SemVer/changelog policy, TDD rules,
  architecture and design-pattern skills ([software-foundation](./docs/software-foundation.md))
- CI/release verification via `tests.test_software_foundation`, gitignore and video-use trace tests
- Software quality refactor: pytest as canonical runner, full-suite CI parity,
  enhanced `release.yml` (version check + GitHub Release), [quality audit](./docs/software-quality-audit.md)
- Test layout: AVO core vs `tests/projects/` (footage-project specs excluded from CI via `pytest -m "not project"`)
