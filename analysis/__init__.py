"""Health Data Hub analysis engine.

Two-brain architecture:

1. ``analysis.statistical`` — SQL-driven aggregation, anomaly detection,
   trend analysis, correlation analysis, baselines, and composite score
   computation. Pure numeric output, no natural language.

2. ``analysis.llm`` — LiteLLM-based narrator that turns structured
   findings into short, safety-reviewed narratives.

Phase 1 ships the package skeleton only. Every class has the right
shape and docstring, but methods that require real numeric work or
live LLM calls raise ``NotImplementedError`` with a pointer to Phase
1.5 where the actual implementations land.

Dependency direction: ``analysis`` may import from ``server.db``
(shared engine + session), but ``server`` must never import from
``analysis`` at runtime. ``server.api.insights`` only imports types.
"""
