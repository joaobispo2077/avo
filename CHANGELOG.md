## [1.1.1](https://github.com/joaobispo2077/avo/compare/v1.1.0...v1.1.1) (2026-08-02)


### Bug Fixes

* **release:** accept H1 linked changelog headings and drop develop alphas ([57bf96e](https://github.com/joaobispo2077/avo/commit/57bf96e206b5225b4087d37c8d2265b5ebd90b3f))

# [1.1.0](https://github.com/joaobispo2077/avo/compare/v1.0.1...v1.1.0) (2026-08-02)


### Bug Fixes

* **release:** accept semantic-release changelog headings in verify step ([1dd3201](https://github.com/joaobispo2077/avo/commit/1dd3201766cf222e9bf17fc539d831abd46d5005))
* **render:** apply yuva420p before overlay scale in composite graph ([80386c4](https://github.com/joaobispo2077/avo/commit/80386c456305a793c2208d3095becf90203c90c1))


### Features

* **docs:** add HyperFrames product-promo motion knowledge exemplars ([244fb37](https://github.com/joaobispo2077/avo/commit/244fb37ca9ae8ed68505a6b8d5562255254de1cb))
* **docs:** add HyperFrames short-form vertical motion knowledge exemplars ([c83a55a](https://github.com/joaobispo2077/avo/commit/c83a55a345c88403289e6e518e358abcb3558d30))
* **ci:** lint HyperFrames exemplar compositions in unit test job ([bd01cd5](https://github.com/joaobispo2077/avo/commit/bd01cd547867088818ce0bd379f9359831f18997))

## [1.0.1](https://github.com/joaobispo2077/avo/compare/v1.0.0...v1.0.1) (2026-08-02)
# 1.0.0-alpha.1 (2026-08-02)


### Bug Fixes

* **release:** accept semantic-release changelog headings in verify step ([c009702](https://github.com/joaobispo2077/avo/commit/c0097022ac240fb241545652048f439c7432c898))
* **release:** accept semantic-release changelog headings in verify step ([1dd3201](https://github.com/joaobispo2077/avo/commit/1dd3201766cf222e9bf17fc539d831abd46d5005))
* **validate-edl:** add tracked EDL JSON schema for CI validation ([7414515](https://github.com/joaobispo2077/avo/commit/7414515942423e3ca208a6b47ac912d5b647ddfd))
* **test:** add tracked locale stub for avo.locale stop gate ([ae5e75a](https://github.com/joaobispo2077/avo/commit/ae5e75a20560f0d49435c764568338577e7db9d3))
* **render:** apply yuva420p before overlay scale in composite graph ([80386c4](https://github.com/joaobispo2077/avo/commit/80386c456305a793c2208d3095becf90203c90c1))
* **release:** detect merge commits and use develop branch ([84b2392](https://github.com/joaobispo2077/avo/commit/84b23927d79f9185499dbd12da3e85ba09255e56))
* **install:** detect node on Linux via shell command -v ([c8ef247](https://github.com/joaobispo2077/avo/commit/c8ef2479228aad1117e6823aa97f922b90e76873))
* **release:** fix workflow_run branch detection and dedupe release triggers ([a837c16](https://github.com/joaobispo2077/avo/commit/a837c163353a5b501e0cb6fcacc54d167965585b))
* **release:** isolate concurrency by CI event to avoid cancel race ([663e698](https://github.com/joaobispo2077/avo/commit/663e698555fa51419c639d22cf39b60525553ae4))
* **release:** load pyproject sync as external semantic-release plugin ([c691588](https://github.com/joaobispo2077/avo/commit/c691588714f2bd02056399c23b68b27cd6fb9f1f))
* **release:** parse dry-run version and verify from package.json ([11b3478](https://github.com/joaobispo2077/avo/commit/11b3478d23dae616ae63e87e280adfb531e29140))
* **release:** parse first-release dry-run version case-insensitively ([2132aee](https://github.com/joaobispo2077/avo/commit/2132aee324f936876365a729e708dc052115d7b7))
* **render:** preserve orientation for portrait video sources ([#29](https://github.com/joaobispo2077/avo/issues/29)) ([1200463](https://github.com/joaobispo2077/avo/commit/1200463f00ae53fa562dc8ca2b5f8b7ec7d43f43))
* **release:** publish stable from release branch instead of main ([415aab1](https://github.com/joaobispo2077/avo/commit/415aab1962455f991f6b0dd6d04317029dcdf910))
* **subtitles:** raise MarginV to 90 to clear vertical safe zones ([#5](https://github.com/joaobispo2077/avo/issues/5)) ([87f00c6](https://github.com/joaobispo2077/avo/commit/87f00c6b9b4199dadf3c3b7a75bf818f3df0695e))
* **release:** resolve pyproject sync script from repo root ([33beb80](https://github.com/joaobispo2077/avo/commit/33beb8000ca2add5357c2fe15ce9033b093e994c))
* **render:** tone-map HLG/PQ sources to Rec.709 SDR ([#6](https://github.com/joaobispo2077/avo/issues/6)) ([60798b1](https://github.com/joaobispo2077/avo/commit/60798b1cd5cd4563875aeb06bb9252983084831a))
* **release:** treat matching pyproject version as sync success ([7607fe5](https://github.com/joaobispo2077/avo/commit/7607fe52a7b222bf5b7e1a4286a6758e6defbf93))
* **test:** use ASCII locale stub assertion to avoid encoding mismatch on CI ([5b597e8](https://github.com/joaobispo2077/avo/commit/5b597e839f3fca751093a581741ff56332bff757))
* **pack_transcripts:** write output as UTF-8 to avoid cp1252 encoding errors ([#10](https://github.com/joaobispo2077/avo/issues/10)) ([196d7e9](https://github.com/joaobispo2077/avo/commit/196d7e9377d7265ae61bd9e6189a4b12f33913c1))


### Features

* **commands:** add /avo.rights and /avo.audio-qc slash commands ([1728a4e](https://github.com/joaobispo2077/avo/commit/1728a4eaa47cd746be68938b0a244cc84fb8ff52))
* **commands:** add avo.captions and avo.deliver pipeline slices ([4ebea27](https://github.com/joaobispo2077/avo/commit/4ebea277118a90f56af0fc0b2040a308db9318bc))
* **commands:** add avo.shorts orchestrator and avo.reframe slice ([69a6b9e](https://github.com/joaobispo2077/avo/commit/69a6b9e9d9d7b479f710f688a2ecfe5fe6068490))
* **docs:** add HyperFrames product-promo motion knowledge exemplars ([244fb37](https://github.com/joaobispo2077/avo/commit/244fb37ca9ae8ed68505a6b8d5562255254de1cb))
* **docs:** add HyperFrames short-form vertical motion knowledge exemplars ([c83a55a](https://github.com/joaobispo2077/avo/commit/c83a55a345c88403289e6e518e358abcb3558d30))
* **commands:** add wave-2 AVO slash commands for upload prep, formats, and content routers ([a8448f3](https://github.com/joaobispo2077/avo/commit/a8448f3440de4cf6b78974d29fe902cc06b01c2a))
* **commands:** add wave-3 AVO slash commands ([5f1a8fe](https://github.com/joaobispo2077/avo/commit/5f1a8fe4cf01de6b5de8dc4c74c7e659c3e24c6b))
* **commands:** add wave-4 AVO slash commands ([2d4a4e3](https://github.com/joaobispo2077/avo/commit/2d4a4e38babcb8aadb249e44b8e4adfcc678f4aa))
* **ci:** lint HyperFrames exemplar compositions in unit test job ([bd01cd5](https://github.com/joaobispo2077/avo/commit/bd01cd547867088818ce0bd379f9359831f18997))

# 1.0.0 (2026-08-02)


### Bug Fixes

* **validate-edl:** add tracked EDL JSON schema for CI validation ([7414515](https://github.com/joaobispo2077/avo/commit/7414515942423e3ca208a6b47ac912d5b647ddfd))
* **test:** add tracked locale stub for avo.locale stop gate ([ae5e75a](https://github.com/joaobispo2077/avo/commit/ae5e75a20560f0d49435c764568338577e7db9d3))
* **release:** detect merge commits and use develop branch ([84b2392](https://github.com/joaobispo2077/avo/commit/84b23927d79f9185499dbd12da3e85ba09255e56))
* **install:** detect node on Linux via shell command -v ([c8ef247](https://github.com/joaobispo2077/avo/commit/c8ef2479228aad1117e6823aa97f922b90e76873))
* **release:** fix workflow_run branch detection and dedupe release triggers ([a837c16](https://github.com/joaobispo2077/avo/commit/a837c163353a5b501e0cb6fcacc54d167965585b))
* **release:** isolate concurrency by CI event to avoid cancel race ([663e698](https://github.com/joaobispo2077/avo/commit/663e698555fa51419c639d22cf39b60525553ae4))
* **release:** load pyproject sync as external semantic-release plugin ([c691588](https://github.com/joaobispo2077/avo/commit/c691588714f2bd02056399c23b68b27cd6fb9f1f))
* **release:** parse dry-run version and verify from package.json ([11b3478](https://github.com/joaobispo2077/avo/commit/11b3478d23dae616ae63e87e280adfb531e29140))
* **release:** parse first-release dry-run version case-insensitively ([2132aee](https://github.com/joaobispo2077/avo/commit/2132aee324f936876365a729e708dc052115d7b7))
* **render:** preserve orientation for portrait video sources ([#29](https://github.com/joaobispo2077/avo/issues/29)) ([1200463](https://github.com/joaobispo2077/avo/commit/1200463f00ae53fa562dc8ca2b5f8b7ec7d43f43))
* **release:** publish stable from release branch instead of main ([415aab1](https://github.com/joaobispo2077/avo/commit/415aab1962455f991f6b0dd6d04317029dcdf910))
* **subtitles:** raise MarginV to 90 to clear vertical safe zones ([#5](https://github.com/joaobispo2077/avo/issues/5)) ([87f00c6](https://github.com/joaobispo2077/avo/commit/87f00c6b9b4199dadf3c3b7a75bf818f3df0695e))
* **release:** resolve pyproject sync script from repo root ([33beb80](https://github.com/joaobispo2077/avo/commit/33beb8000ca2add5357c2fe15ce9033b093e994c))
* **render:** tone-map HLG/PQ sources to Rec.709 SDR ([#6](https://github.com/joaobispo2077/avo/issues/6)) ([60798b1](https://github.com/joaobispo2077/avo/commit/60798b1cd5cd4563875aeb06bb9252983084831a))
* **release:** treat matching pyproject version as sync success ([7607fe5](https://github.com/joaobispo2077/avo/commit/7607fe52a7b222bf5b7e1a4286a6758e6defbf93))
* **test:** use ASCII locale stub assertion to avoid encoding mismatch on CI ([5b597e8](https://github.com/joaobispo2077/avo/commit/5b597e839f3fca751093a581741ff56332bff757))
* **pack_transcripts:** write output as UTF-8 to avoid cp1252 encoding errors ([#10](https://github.com/joaobispo2077/avo/issues/10)) ([196d7e9](https://github.com/joaobispo2077/avo/commit/196d7e9377d7265ae61bd9e6189a4b12f33913c1))


### Features

* **commands:** add /avo.rights and /avo.audio-qc slash commands ([1728a4e](https://github.com/joaobispo2077/avo/commit/1728a4eaa47cd746be68938b0a244cc84fb8ff52))
* **commands:** add avo.captions and avo.deliver pipeline slices ([4ebea27](https://github.com/joaobispo2077/avo/commit/4ebea277118a90f56af0fc0b2040a308db9318bc))
* **commands:** add avo.shorts orchestrator and avo.reframe slice ([69a6b9e](https://github.com/joaobispo2077/avo/commit/69a6b9e9d9d7b479f710f688a2ecfe5fe6068490))
* **commands:** add wave-2 AVO slash commands for upload prep, formats, and content routers ([a8448f3](https://github.com/joaobispo2077/avo/commit/a8448f3440de4cf6b78974d29fe902cc06b01c2a))
* **commands:** add wave-3 AVO slash commands ([5f1a8fe](https://github.com/joaobispo2077/avo/commit/5f1a8fe4cf01de6b5de8dc4c74c7e659c3e24c6b))
* **commands:** add wave-4 AVO slash commands ([2d4a4e3](https://github.com/joaobispo2077/avo/commit/2d4a4e38babcb8aadb249e44b8e4adfcc678f4aa))

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
