"""Small value objects shared by ingest plugins and storage backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IngestWriteResult:
    """Storage write accounting for one ingest operation.

    ``accepted`` keeps the legacy meaning: valid samples/rows the backend
    processed. ``inserted_new`` and ``deduped_existing`` are optional because
    non-Postgres backends or older writers may only know the legacy accepted
    count.
    """

    accepted: int = 0
    inserted_new: int | None = None
    deduped_existing: int | None = None

    @property
    def storage_result_level(self) -> str:
        if self.inserted_new is not None and self.deduped_existing is not None:
            return "inserted_vs_existing"
        return "accepted_only"

    def with_insert_flag(self, inserted_new: bool | None) -> "IngestWriteResult":
        if inserted_new is None:
            return IngestWriteResult(accepted=self.accepted + 1)
        return IngestWriteResult(
            accepted=self.accepted + 1,
            inserted_new=(self.inserted_new or 0) + (1 if inserted_new else 0),
            deduped_existing=(self.deduped_existing or 0) + (0 if inserted_new else 1),
        )

    def combine(self, other: int | "IngestWriteResult") -> "IngestWriteResult":
        other_result = coerce_ingest_result(other)
        return IngestWriteResult(
            accepted=self.accepted + other_result.accepted,
            inserted_new=_combine_optional(
                self.inserted_new,
                other_result.inserted_new,
                self.accepted,
                other_result.accepted,
            ),
            deduped_existing=_combine_optional(
                self.deduped_existing,
                other_result.deduped_existing,
                self.accepted,
                other_result.accepted,
            ),
        )

    def to_plugin_result(self, *, rejected: int = 0) -> dict[str, int | str | None]:
        return {
            "accepted": self.accepted,
            "rejected": rejected,
            "inserted_new": self.inserted_new,
            "deduped_existing": self.deduped_existing,
            "storage_result_level": self.storage_result_level,
        }

    def __int__(self) -> int:
        return self.accepted

    def __radd__(self, other: int) -> int:
        return other + self.accepted

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, int):
            return self.accepted == other
        if isinstance(other, IngestWriteResult):
            return (
                self.accepted,
                self.inserted_new,
                self.deduped_existing,
            ) == (
                other.accepted,
                other.inserted_new,
                other.deduped_existing,
            )
        return False


def coerce_ingest_result(value: int | IngestWriteResult) -> IngestWriteResult:
    if isinstance(value, IngestWriteResult):
        return value
    return IngestWriteResult(accepted=int(value))


def _combine_optional(
    left: int | None,
    right: int | None,
    left_accepted: int,
    right_accepted: int,
) -> int | None:
    if left is None and left_accepted > 0:
        return None
    if right is None and right_accepted > 0:
        return None
    return (left or 0) + (right or 0)
