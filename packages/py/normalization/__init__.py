"""Source-to-canonical normalization.

Pure functions that turn a raw source payload into canonical
:class:`contracts.observation.Observation` records, driven entirely by the
metric ontology (the registry's per-source vocabulary mappings). No DB, no
network — testable against the golden payload corpus and replayable.
"""

from .apple import (
    NORMALIZER_ID,
    NORMALIZER_VERSION,
    NormalizeResult,
    Rejection,
    normalize_apple_batch,
)

__all__ = [
    "NORMALIZER_ID",
    "NORMALIZER_VERSION",
    "NormalizeResult",
    "Rejection",
    "normalize_apple_batch",
]
