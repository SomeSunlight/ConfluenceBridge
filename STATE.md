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
