/**
 * AUTO-GENERATED — do not edit.
 *
 * Regenerate via:
 *   make regen-ts-client
 *
 * Source of truth:
 *   contracts/json-schema/_bundle.json
 */
export type Loinc = string;
export type Name = string;
export type Unit = string;
export type Markers = LabImportMarker[];
export type CreatedAt = string;
export type FileName = string;
export type Id = string;
export type OwnerId = string;
export type Method = "text" | "ocr" | "csv";
export type Page = number;
export type Text = string;
export type Pages = LabDocumentPage[];
export type Confirmed = boolean;
export type Lab = string;
export type Loinc1 = string;
export type MarkerName = string;
export type Panel = string;
export type ReferenceHigh = string;
export type ReferenceLow = string;
export type RowId = string;
export type SpecimenDatetime = string;
export type Unit1 = string;
export type Value = string;
export type Rows = LabReviewRow[];
export type Sha256 = string;
export type Status = "draft" | "committed";
export type Warnings = string[];
export type WorkspaceId = string;
export type CommittedAt = string | null;
export type CreatedAt1 = string;
export type FileName1 = string;
export type Id1 = string;
export type Sha2561 = string;
export type Documents = LabImportIndexItem[];
export type OwnerId1 = string;
export type WorkspaceId1 = string;
export type Id2 = string;
export type Inserted = number;
export type OwnerId2 = string;
export type ReportUrl = string;
export type ResultCount = number;
export type Unchanged = number;
export type Updated = number;
export type WorkspaceId2 = string;
export type FileName2 = string;
export type Id3 = string;
export type ImportedAt = string;
export type Limitations = string[];
export type OwnerId3 = string;
export type ReportVersion = string;
export type Comparator = string | null;
export type Lab1 = string;
export type Loinc2 = string;
export type Marker = string;
export type MeasurementQuality = string;
export type MedicalEvidence = string;
export type Observation = string;
export type PersonalPattern = string;
export type QualityFlags = string[];
export type ReferenceHigh1 = number | null;
export type ReferenceLow1 = number | null;
export type SourceExcerpt = string | null;
export type SourceIds = string[];
export type SourcePage = number | null;
export type SpecimenAt = string;
export type Unit2 = string;
export type Value1 = number;
export type Results = LabReportResult[];
export type ReviewStatus = string;
export type Sha2562 = string;
export type AccessedOn = string;
export type Id4 = string;
export type Scope = string;
export type Title = string;
export type Url = string;
export type Sources = LabEvidenceSource[];
export type WorkspaceId3 = string;
export type OwnerId4 = string;
/**
 * @minItems 1
 * @maxItems 250
 */
export type Rows1 = [LabReviewRow, ...LabReviewRow[]];
export type WorkspaceId4 = string;


export interface LabImportCatalog {
  markers: Markers;
}
export interface LabImportMarker {
  loinc: Loinc;
  name: Name;
  unit: Unit;
}
export interface LabImportDraft {
  created_at: CreatedAt;
  file_name: FileName;
  id: Id;
  owner_id?: OwnerId;
  pages: Pages;
  rows: Rows;
  sha256: Sha256;
  status: Status;
  warnings: Warnings;
  workspace_id?: WorkspaceId;
}
export interface LabDocumentPage {
  method: Method;
  page: Page;
  text: Text;
}
export interface LabReviewRow {
  confirmed?: Confirmed;
  lab?: Lab;
  loinc?: Loinc1;
  marker_name?: MarkerName;
  panel?: Panel;
  reference_high?: ReferenceHigh;
  reference_low?: ReferenceLow;
  row_id: RowId;
  specimen_datetime?: SpecimenDatetime;
  unit?: Unit1;
  value?: Value;
}
export interface LabImportIndex {
  documents: Documents;
  owner_id?: OwnerId1;
  workspace_id?: WorkspaceId1;
}
export interface LabImportIndexItem {
  committed_at: CommittedAt;
  created_at: CreatedAt1;
  file_name: FileName1;
  id: Id1;
  sha256: Sha2561;
}
export interface LabImportReceipt {
  id: Id2;
  inserted: Inserted;
  owner_id?: OwnerId2;
  report_url: ReportUrl;
  result_count: ResultCount;
  unchanged: Unchanged;
  updated: Updated;
  workspace_id?: WorkspaceId2;
}
export interface LabImportReport {
  file_name: FileName2;
  id: Id3;
  imported_at: ImportedAt;
  limitations: Limitations;
  owner_id?: OwnerId3;
  report_version: ReportVersion;
  results: Results;
  review_status: ReviewStatus;
  sha256: Sha2562;
  sources: Sources;
  workspace_id?: WorkspaceId3;
}
export interface LabReportResult {
  comparator: Comparator;
  lab: Lab1;
  loinc: Loinc2;
  marker: Marker;
  measurement_quality: MeasurementQuality;
  medical_evidence: MedicalEvidence;
  observation: Observation;
  personal_pattern: PersonalPattern;
  quality_flags: QualityFlags;
  reference_high: ReferenceHigh1;
  reference_low: ReferenceLow1;
  source_excerpt: SourceExcerpt;
  source_ids: SourceIds;
  source_page: SourcePage;
  specimen_at: SpecimenAt;
  unit: Unit2;
  value: Value1;
}
export interface LabEvidenceSource {
  accessed_on: AccessedOn;
  id: Id4;
  scope: Scope;
  title: Title;
  url: Url;
}
export interface LabImportReview {
  owner_id?: OwnerId4;
  rows: Rows1;
  workspace_id?: WorkspaceId4;
}
