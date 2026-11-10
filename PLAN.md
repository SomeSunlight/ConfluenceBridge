# Plan — Issue #2: explicit ConfluenceBridge source version check

Purpose: give the separate Confluence export/PDF scripts one lightweight, dependency-free executable source identity and the same optional GitHub check as ContextCanon and github-local. The check must not read Confluence credentials or touch exported workspaces.

- [x] Check current main, Issue #2, script architecture, packaging version, tests and dependencies.
- [x] Introduce one canonical source release version (3.0.1 from CHANGELOG), reconcile stale setup.py metadata (0.0.1), and add a small standalone version CLI without refactoring exporter scripts.
- [x] Implement offline Git SHA/branch/dirty and PEP 610 provenance and explicit network-only version check with 0/1/2 exit codes and fail-closed unknown status.
- [x] Add deterministic mocked-network, no-export/no-credentials and checkout/PEP-610 regressions. Python 3.11/3.12 on Ubuntu and Windows passed ([CI run #42858067060](https://github.com/SomeSunlight/ConfluenceBridge/actions/runs/42858067060)).
- [x] Document CLI installation, command examples and deliberate upgrade procedure.
- [x] Pass matrix CI at commit `7528e4a`: four OS/Python combinations plus a real uv Git-URL commit/branch install; publish [Draft PR #3](https://github.com/SomeSunlight/ConfluenceBridge/pull/3). This docs-only checkpoint will receive its own exact-head rerun. No merge without owner approval.
- [x] Track actual ContextCanon source inheritance as separate Issue #4; no implicit onboarding bundled into this PR.
- [ ] Post-merge baseline checkpoint after owner acceptance.

Constraint: this repository is not yet onboarded in ContextCanon. Reuse the accepted Development Workflow documentation directly and keep full ContextCanon onboarding separate from this focused CLI change.
