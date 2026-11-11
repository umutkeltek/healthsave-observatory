"""Private, explicitly reviewed laboratory document imports."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from ._base import V2Model, WithOwnership


class LabReviewRow(V2Model):
    row_id: str = Field(min_length=1, max_length=80)
    specimen_datetime: str = Field(default="", max_length=80)
    loinc: str = Field(default="", max_length=20)
    marker_name: str = Field(default="", max_length=160)
    value: str = Field(default="", max_length=80)
    unit: str = Field(default="", max_length=80)
    reference_low: str = Field(default="", max_length=80)
    reference_high: str = Field(default="", max_length=80)
    lab: str = Field(default="", max_length=160)
    panel: str = Field(default="", max_length=160)
    confirmed: bool = False


class LabDocumentPage(V2Model):
    page: int
    text: str
    method: Literal["text", "ocr", "csv"]


class LabImportDraft(WithOwnership):
    id: UUID
    file_name: str
    sha256: str
    created_at: datetime
    status: Literal["draft", "committed"]
    pages: list[LabDocumentPage]
    rows: list[LabReviewRow]
    warnings: list[str]


class LabImportReview(WithOwnership):
    rows: list[LabReviewRow] = Field(min_length=1, max_length=250)


class LabImportIndexItem(V2Model):
    id: UUID
    file_name: str
    sha256: str
    created_at: datetime
    committed_at: datetime | None


class LabImportIndex(WithOwnership):
    documents: list[LabImportIndexItem]


class LabImportMarker(V2Model):
    loinc: str
    name: str
    unit: str


class LabImportCatalog(V2Model):
    markers: list[LabImportMarker]


class LabImportReceipt(WithOwnership):
    id: UUID
    inserted: int
    updated: int
    unchanged: int
    result_count: int
    report_url: str


class LabEvidenceSource(V2Model):
    id: str
    title: str
    url: str
    accessed_on: str
    scope: str


class LabReportResult(V2Model):
    marker: str
    loinc: str
    specimen_at: datetime
    lab: str
    value: float
    comparator: str | None
    unit: str
    reference_low: float | None
    reference_high: float | None
    observation: str
    measurement_quality: str
    personal_pattern: str
    medical_evidence: str
    source_page: int | None
    source_excerpt: str | None
    quality_flags: list[str]
    source_ids: list[str]


class LabImportReport(WithOwnership):
    id: UUID
    file_name: str
    sha256: str
    imported_at: datetime
    report_version: str
    review_status: str
    limitations: list[str]
    results: list[LabReportResult]
    sources: list[LabEvidenceSource]
