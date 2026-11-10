# Plan — Issue #2: explicit ConfluenceBridge source version check

Purpose: give the separate Confluence export/PDF scripts one lightweight, dependency-free executable source identity and the same optional GitHub check as ContextCanon and github-local. The check must not read Confluence credentials or touch exported workspaces.

- [x] Check current main, Issue #2, script architecture, packaging version, tests and dependencies.
- [x] Introduce one canonical source release version (3.0.1 from CHANGELOG), reconcile stale setup.py metadata (0.0.1), and add a small standalone version CLI without refactoring exporter scripts.
- [x] Implement offline Git SHA/branch/dirty and PEP 610 provenance and explicit network-only version check with 0/1/2 exit codes and fail-closed unknown status.
- [ ] Add deterministic mocked-network and no-export/no-credentials regressions; test Linux/Windows.
- [ ] Document CLI installation, command examples and deliberate upgrade procedure.
- [ ] Pass exact-head review CI; present draft PR for owner testing. No merge without approval.
- [ ] Post-merge baseline checkpoint after owner acceptance.

Constraint: this repository is not yet onboarded in ContextCanon. Reuse the accepted Development Workflow documentation directly and keep full ContextCanon onboarding separate from this focused CLI change.
