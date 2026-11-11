"""Private variant evidence retrieval. Classifications belong to the source."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from ._base import V2Model, WithOwnership

Assembly = Literal["GRCh37", "GRCh38"]


class GeneticReference(V2Model):
    assembly: Assembly
    release_date: str
    sha256: str
    source_url: str
    installed_at: datetime
    record_count: int
    excluded_reference_records: int
    index_version: str


class GeneticReferenceJob(V2Model):
    state: Literal["idle", "downloading", "indexing", "complete", "failed", "interrupted"]
    assembly: Assembly | None = None
    message: str = ""
    bytes_downloaded: int = 0
    records_indexed: int = 0
    started_at: str | None = None


class GeneticReferenceStatus(V2Model):
    references: list[GeneticReference]
    job: GeneticReferenceJob


class GeneticReferenceUpdate(WithOwnership):
    assembly: Assembly
    confirmed: bool = False


class GeneticAnnotation(V2Model):
    chromosome: str
    position: int
    genotype: str
    reference: str
    alternate: str
    alternate_copies: int
    variation_id: str
    gene: str
    conditions: str
    source_classification: str
    source_review_status: str
    review_stars: int = Field(ge=0, le=4)
    conflicting: bool
    category: Literal["pathogenic", "benign", "uncertain", "conflicting", "other"]
    call_quality: str
    depth: int | None
    genotype_quality: float | None
    hgvs: str
    source_url: str
    details_truncated: bool


class GeneticReport(WithOwnership):
    id: UUID
    document_id: UUID
    created_at: datetime
    engine_version: str
    file_name: str
    input_sha256: str
    input_format: str
    assembly: Assembly
    assembly_in_file: bool
    input_counts: dict[str, int]
    reference: GeneticReference
    annotations: list[GeneticAnnotation]
    matched_loci: int
    matched_annotations: int
    unmatched_loci: int
    reference_mismatch_loci: int
    omitted_annotations: int
    warnings: list[str]
    limitations: list[str]


class GeneticDocument(WithOwnership):
    id: UUID
    file_name: str
    sha256: str
    assembly: Assembly
    created_at: datetime
    original_retained: bool


class GeneticReportVersion(V2Model):
    id: UUID
    created_at: datetime
    reference_release: str
    engine_version: str


class GeneticDocumentDetail(WithOwnership):
    document: GeneticDocument
    report: GeneticReport
    reports: list[GeneticReportVersion]


class GeneticIndex(WithOwnership):
    documents: list[GeneticDocument]


class GeneticReanalysis(WithOwnership):
    confirmed: bool = False


class GeneticDeletion(WithOwnership):
    confirmation: UUID


class GeneticDeletionReceipt(WithOwnership):
    id: UUID
    deleted_reports: int
