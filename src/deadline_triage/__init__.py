"""Court deadline triage from Brazil's national electronic gazette (DJEN).

Batch pipeline: fetch publications by bar number -> classify the deadline type with a language
model -> decide by catalogue rules -> compute the due date with a deterministic engine over
versioned court calendars -> hand a triage row to a lawyer for confirmation. See README.md.
"""
