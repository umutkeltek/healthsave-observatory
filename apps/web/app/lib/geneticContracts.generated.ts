/**
 * AUTO-GENERATED — do not edit.
 *
 * Regenerate via:
 *   make regen-ts-client
 *
 * Source of truth:
 *   contracts/json-schema/_bundle.json
 */
export type Alternate = string;
export type AlternateCopies = number;
export type CallQuality = string;
export type Category = "pathogenic" | "benign" | "uncertain" | "conflicting" | "other";
export type Chromosome = string;
export type Conditions = string;
export type Conflicting = boolean;
export type Depth = number | null;
export type DetailsTruncated = boolean;
export type Gene = string;
export type Genotype = string;
export type GenotypeQuality = number | null;
export type Hgvs = string;
export type Position = number;
export type Reference = string;
export type ReviewStars = number;
export type SourceClassification = string;
export type SourceReviewStatus = string;
export type SourceUrl = string;
export type VariationId = string;
export type Confirmation = string;
export type OwnerId = string;
export type WorkspaceId = string;
export type DeletedReports = number;
export type Id = string;
export type OwnerId1 = string;
export type WorkspaceId1 = string;
export type Assembly = "GRCh37" | "GRCh38";
export type CreatedAt = string;
export type FileName = string;
export type Id1 = string;
export type OriginalRetained = boolean;
export type OwnerId2 = string;
export type Sha256 = string;
export type WorkspaceId2 = string;
export type OwnerId3 = string;
export type Annotations = GeneticAnnotation[];
export type Assembly1 = "GRCh37" | "GRCh38";
export type AssemblyInFile = boolean;
export type CreatedAt1 = string;
export type DocumentId = string;
export type EngineVersion = string;
export type FileName1 = string;
export type Id2 = string;
export type InputFormat = string;
export type InputSha256 = string;
export type Limitations = string[];
export type MatchedAnnotations = number;
export type MatchedLoci = number;
export type OmittedAnnotations = number;
export type OwnerId4 = string;
export type Assembly2 = "GRCh37" | "GRCh38";
export type ExcludedReferenceRecords = number;
export type IndexVersion = string;
export type InstalledAt = string;
export type RecordCount = number;
export type ReleaseDate = string;
export type Sha2561 = string;
export type SourceUrl1 = string;
export type ReferenceMismatchLoci = number;
export type UnmatchedLoci = number;
export type Warnings = string[];
export type WorkspaceId3 = string;
export type CreatedAt2 = string;
export type EngineVersion1 = string;
export type Id3 = string;
export type ReferenceRelease = string;
export type Reports = GeneticReportVersion[];
export type WorkspaceId4 = string;
export type Documents = GeneticDocument[];
export type NextCursor = string | null;
export type OwnerId5 = string;
export type WorkspaceId5 = string;
export type Confirmed = boolean;
export type OwnerId6 = string;
export type WorkspaceId6 = string;
export type Assembly3 = ("GRCh37" | "GRCh38") | null;
export type BytesDownloaded = number;
export type Message = string;
export type RecordsIndexed = number;
export type StartedAt = string | null;
export type State = "idle" | "downloading" | "indexing" | "complete" | "failed" | "interrupted";
export type References = GeneticReference[];
export type Assembly4 = "GRCh37" | "GRCh38";
export type Confirmed1 = boolean;
export type OwnerId7 = string;
export type WorkspaceId7 = string;


export interface GeneticAnnotation {
  alternate: Alternate;
  alternate_copies: AlternateCopies;
  call_quality: CallQuality;
  category: Category;
  chromosome: Chromosome;
  conditions: Conditions;
  conflicting: Conflicting;
  depth: Depth;
  details_truncated: DetailsTruncated;
  gene: Gene;
  genotype: Genotype;
  genotype_quality: GenotypeQuality;
  hgvs: Hgvs;
  position: Position;
  reference: Reference;
  review_stars: ReviewStars;
  source_classification: SourceClassification;
  source_review_status: SourceReviewStatus;
  source_url: SourceUrl;
  variation_id: VariationId;
}
export interface GeneticDeletion {
  confirmation: Confirmation;
  owner_id?: OwnerId;
  workspace_id?: WorkspaceId;
}
export interface GeneticDeletionReceipt {
  deleted_reports: DeletedReports;
  id: Id;
  owner_id?: OwnerId1;
  workspace_id?: WorkspaceId1;
}
export interface GeneticDocument {
  assembly: Assembly;
  created_at: CreatedAt;
  file_name: FileName;
  id: Id1;
  original_retained: OriginalRetained;
  owner_id?: OwnerId2;
  sha256: Sha256;
  workspace_id?: WorkspaceId2;
}
export interface GeneticDocumentDetail {
  document: GeneticDocument;
  owner_id?: OwnerId3;
  report: GeneticReport;
  reports: Reports;
  workspace_id?: WorkspaceId4;
}
export interface GeneticReport {
  annotations: Annotations;
  assembly: Assembly1;
  assembly_in_file: AssemblyInFile;
  created_at: CreatedAt1;
  document_id: DocumentId;
  engine_version: EngineVersion;
  file_name: FileName1;
  id: Id2;
  input_counts: InputCounts;
  input_format: InputFormat;
  input_sha256: InputSha256;
  limitations: Limitations;
  matched_annotations: MatchedAnnotations;
  matched_loci: MatchedLoci;
  omitted_annotations: OmittedAnnotations;
  owner_id?: OwnerId4;
  reference: GeneticReference;
  reference_mismatch_loci: ReferenceMismatchLoci;
  unmatched_loci: UnmatchedLoci;
  warnings: Warnings;
  workspace_id?: WorkspaceId3;
}
export interface InputCounts {
  [k: string]: number;
}
export interface GeneticReference {
  assembly: Assembly2;
  excluded_reference_records: ExcludedReferenceRecords;
  index_version: IndexVersion;
  installed_at: InstalledAt;
  record_count: RecordCount;
  release_date: ReleaseDate;
  sha256: Sha2561;
  source_url: SourceUrl1;
}
export interface GeneticReportVersion {
  created_at: CreatedAt2;
  engine_version: EngineVersion1;
  id: Id3;
  reference_release: ReferenceRelease;
}
export interface GeneticIndex {
  documents: Documents;
  next_cursor?: NextCursor;
  owner_id?: OwnerId5;
  workspace_id?: WorkspaceId5;
}
export interface GeneticReanalysis {
  confirmed?: Confirmed;
  owner_id?: OwnerId6;
  workspace_id?: WorkspaceId6;
}
export interface GeneticReferenceJob {
  assembly?: Assembly3;
  bytes_downloaded?: BytesDownloaded;
  message?: Message;
  records_indexed?: RecordsIndexed;
  started_at?: StartedAt;
  state: State;
}
export interface GeneticReferenceStatus {
  job: GeneticReferenceJob;
  references: References;
}
export interface GeneticReferenceUpdate {
  assembly: Assembly4;
  confirmed?: Confirmed1;
  owner_id?: OwnerId7;
  workspace_id?: WorkspaceId7;
}
