## Review candidate — tool source provenance (Issue #2)

ConfluenceBridge currently keeps its export and publication scripts independent. Issue #2 adds a **separate, lightweight version command** that neither imports the export engines nor interacts with Confluence, API tokens, browser sessions or existing workspace manifests. The canonical application version is 3.0.1 (see CHANGELOG); older setup.py still had the original upstream package value 0.0.1, which this change reconciles. Offline --version reports the exact executing Git revision, while explicit version check compares it with the public SomeSunlight/ConfluenceBridge GitHub branch. This is independent of Confluence page/manifest versions.

ConfluenceBridge does not yet have a ContextCanon Node. The accepted Development Workflow's CCW-017 semantics are applied directly for now; a later standalone onboarding block can establish normative Parent inheritance.

# Current State

ConfluenceBridge already has the ETL-based workspace architecture required for Delta-Sync, offline rebuilds, and self-contained workspaces.

At the moment, the normal end-to-end workflow is still split into separate user-facing steps:

1. Download or synchronize the Confluence content.
2. Generate the final PDF from the resulting workspace.

## Next architectural step

Add an orchestration layer that turns these separate operations into one coherent workflow.

The orchestrator should eventually be able to:

- start or resume the Confluence download / Delta-Sync,
- trigger PDF generation after the workspace has been updated,
- later trigger additional output formats such as Markdown,
- keep the self-contained workspace as the common hand-over point between the individual processing stages.

This orchestration layer is not implemented yet. It is the next important step for making the toolbox behave like one integrated export pipeline rather than a collection of separately invoked stages.
