"""Registered WorkflowDefinitions for Phase 5.

Only NEWS_ANALYSIS and CONTENT_GENERATION are defined here. DAILY_DIGEST is
deliberately absent - EditorialTask.event_id is a single foreign key, and a
digest inherently spans many events; registering a workflow that cannot
actually run against the current data model would be technical debt, not
infrastructure. It is added as a complete WorkflowDefinition in a future
Digest Engine phase.
"""
