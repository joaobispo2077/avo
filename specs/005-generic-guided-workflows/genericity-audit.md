# Genericity Audit Checklist

Use this checklist before each story checkpoint and final validation.

- [ ] No private footage, user-home, temporary-project, or repository-local tool checkout path is a generic default.
- [ ] No provider, channel, product, subject, or one-video identifier is embedded in shared runtime code or prompts.
- [ ] No language, video format, editorial style, or acceptance criterion is guessed when it was not declared.
- [ ] No CPU/GPU choice is forced unless an explicit resolved policy requests it.
- [ ] Invocation-only behavior uses a flag; persistent behavior uses a documented validated configuration field.
- [ ] Effective values and their winning scope are inspectable before expensive work without leaking private paths in user summaries.
- [ ] Core tests use neutral providers, subjects, languages, paths, and media; project regressions remain under `tests/projects/`.
- [ ] Legacy files are read/normalized without automatic moves, rewrites, or destructive migration.
- [ ] Canonical path, lineage, approval, rights/disclosure/privacy/safety/AI-use, and QC evidence fail closed when incomplete.
- [ ] Platform-named delivery defaults are verified against current official platform documentation before release.
- [ ] Branches and unrelated user-owned worktree changes remain untouched.
