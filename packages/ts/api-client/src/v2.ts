/**
 * AUTO-GENERATED — do not edit.
 *
 * Regenerate via:
 *   make regen-ts-client
 *
 * Source of truth:
 *   contracts/json-schema/_bundle.json
 */
export type DecidedAt = string;
export type DecidedBy = "user" | "policy" | "auto";
export type Decision = "approved" | "rejected" | "deferred";
export type Id = string;
export type OwnerId = string;
export type ProposalId = string;
export type Rationale = string | null;
export type WorkspaceId = string;
export type DecisionId = string;
export type Error = string | null;
export type ExecutedAt = string;
export type Id1 = string;
export type OwnerId1 = string;
export type ProposalId1 = string;
export type Status = "succeeded" | "failed" | "skipped";
export type WorkspaceId1 = string;
export type ActionKind = "notify" | "create_experiment" | "create_briefing" | "request_user_input" | "tag_measurement";
export type Capability = string;
export type Id2 = string;
export type OwnerId2 = string;
export type ProposedAt = string;
export type Rationale1 = string;
export type RunId = string;
export type WorkspaceId2 = string;
export type CreatedAt = string;
export type Id3 = string;
export type Kind = "narrative" | "chart_spec" | "experiment_plan" | "intervention_proposal";
export type OwnerId3 = string;
export type RunId1 = string;
export type WorkspaceId3 = string;
export type EmittedAt = string;
export type Id4 = string;
export type Kind1 =
  | "run_started"
  | "run_completed"
  | "run_failed"
  | "observation"
  | "proposal_created"
  | "proposal_approved"
  | "proposal_rejected"
  | "execution_succeeded"
  | "execution_failed"
  | "artifact_created";
export type OwnerId4 = string;
export type RunId2 = string | null;
export type WorkspaceId4 = string;
export type EndedAt = string | null;
export type Id5 = string;
export type OwnerId5 = string;
export type PluginId = string;
export type StartedAt = string;
export type Status1 = "running" | "completed" | "failed" | "cancelled";
export type TriggerKind = "cron" | "ingest_event" | "metric_threshold" | "manual";
export type WorkspaceId5 = string;
export type Capabilities = string[];
export type Description = string;
export type Name = string;
export type PluginId1 = string;
export type Triggers = ("cron" | "ingest_event" | "metric_threshold" | "manual")[];
export type Version = string;
export type At = string;
export type Color = string | null;
export type End = string | null;
export type Kind2 = "point" | "range";
export type Text = string;
export type Aggregation = "raw" | "hourly" | "daily";
export type AnnotationsEnabled = boolean;
export type ChartKind = "line" | "bar" | "area" | "scatter";
export type Metric = string;
export type RangeDays = number;
export type Kind3 = "measurement" | "finding" | "observation" | "external";
export type Ref = string;
export type Evidence = EvidenceRef[];
export type Text1 = string;
export type Confidence = number;
export type Reason = string | null;
export type HardwareId = string | null;
export type Id6 = string;
export type Model = string | null;
export type Name1 = string;
export type OwnerId6 = string;
export type SourceId = string;
export type WorkspaceId6 = string;
export type ErrorKind = string;
export type Id7 = string;
export type Message = string;
export type OccurredAt = string;
export type OwnerId7 = string;
export type PayloadRef = string | null;
export type RunId3 = string;
export type WorkspaceId7 = string;
export type EndedAt1 = string | null;
export type ErrorsCount = number;
export type Id8 = string;
export type MeasurementsCount = number;
export type OwnerId8 = string;
export type SourceId1 = string;
export type StartedAt1 = string;
export type Status2 = "running" | "succeeded" | "failed" | "partial" | "cancelled";
export type WorkspaceId8 = string;
export type Claims = Claim[];
export type Metric1 = string | null;
export type Severity = "info" | "watch" | "alert";
export type Summary = string;
export type Confidence1 = number | null;
export type DeviceId = string | null;
export type Id9 = string;
export type IntervalEnd = string;
export type IntervalStart = string;
export type Metric2 = string;
export type NormalizationVersion = string;
export type OwnerId9 = string;
export type CapturedAt = string;
export type RawPayloadRef = string | null;
export type SdkVersion = string;
export type SourcePluginId = string;
export type SourceId2 = string;
export type Unit = string;
export type Value = number;
export type WorkspaceId9 = string;
export type Id10 = string;
export type Insights = Insight[];
export type Kind4 = "daily_briefing" | "weekly_summary" | "anomaly_explanation" | "intervention_proposal";
export type NarratorPluginId = string;
export type NarratorVersion = string;
export type OwnerId10 = string;
export type RenderedAt = string;
export type Rationale2 = string | null;
export type RequiresApproval = boolean;
export type Text2 = string;
export type SuggestedActions = SuggestedAction[];
export type Text3 = string;
export type WorkspaceId10 = string;
export type Annotations = Annotation[];
export type Metric3 = string;
export type OwnerId11 = string;
export type Points = [unknown, unknown][];
export type Unit1 = string;
export type WorkspaceId11 = string;
export type OwnerId12 = string;
export type RawPayloadId = string;
export type WorkspaceId12 = string;
export type CapturedAt1 = string;
export type Id11 = string;
export type Metric4 = string | null;
export type OwnerId13 = string;
export type RunId4 = string;
export type WorkspaceId13 = string;
export type Description1 = string | null;
export type Name2 = string;
export type ConfigSchema = string | null;
export type Consumes = string[];
export type Emits = string[];
export type Entrypoint = string;
export type Id12 = string;
export type Kind5 = "source" | "narrator" | "agent";
export type Language = "python" | "typescript";
export type Name3 = string;
export type Capabilities1 = PluginCapability[];
export type Network = boolean;
export type Secrets = string[];
export type Requires = string[];
export type SdkVersion1 = string;
export type Version1 = string;
export type Id13 = string;
export type OwnerId14 = string;
export type PayloadHash = string;
export type ReceivedAt = string;
export type SourceId3 = string;
export type WorkspaceId14 = string;
export type DisplayName = string;
export type Id14 = string;
export type Kind6 = "sensor" | "manual" | "computed" | "external_api";
export type OwnerId15 = string;
export type PluginId2 = string;
export type WorkspaceId15 = string;
export type AuthRequired = boolean;
export type Delivery = "polling" | "webhook" | "stream";
export type Metrics = string[];
export type PluginId3 = string;
export type RateLimitPerMinute = number | null;


/**
 * The policy layer's verdict on a proposal.
 */
export interface ActionDecision {
  decided_at: DecidedAt;
  decided_by: DecidedBy;
  decision: Decision;
  id: Id;
  owner_id?: OwnerId;
  proposal_id: ProposalId;
  rationale?: Rationale;
  workspace_id?: WorkspaceId;
}
/**
 * The result of executing an approved proposal.
 */
export interface ActionExecution {
  decision_id: DecisionId;
  error?: Error;
  executed_at: ExecutedAt;
  id: Id1;
  owner_id?: OwnerId1;
  proposal_id: ProposalId1;
  result?: Result;
  status: Status;
  workspace_id?: WorkspaceId1;
}
export interface Result {}
/**
 * An action the agent wants to take. Every state mutation begins here.
 *
 * ``capability`` references the manifest-declared capability the
 * agent claims is sufficient to execute this action; the policy
 * layer cross-checks.
 */
export interface ActionProposal {
  action_kind: ActionKind;
  capability: Capability;
  id: Id2;
  owner_id?: OwnerId2;
  payload: Payload;
  proposed_at: ProposedAt;
  rationale: Rationale1;
  run_id: RunId;
  workspace_id?: WorkspaceId2;
}
export interface Payload {}
/**
 * A persisted output of an agent run — narrative, chart, plan.
 */
export interface AgentArtifact {
  created_at: CreatedAt;
  id: Id3;
  kind: Kind;
  owner_id?: OwnerId3;
  payload: Payload1;
  run_id: RunId1;
  workspace_id?: WorkspaceId3;
}
export interface Payload1 {}
/**
 * One event in the agent timeline.
 *
 * Streamed over Server-Sent Events to ``apps/web``'s agent activity
 * feed; persisted as the audit trail. The dashboard reads this
 * shape directly via the generated TS client.
 */
export interface AgentEvent {
  emitted_at: EmittedAt;
  id: Id4;
  kind: Kind1;
  owner_id?: OwnerId4;
  payload: Payload2;
  run_id?: RunId2;
  workspace_id?: WorkspaceId4;
}
export interface Payload2 {}
/**
 * One execution of an agent. The aggregate root for the lifecycle.
 */
export interface AgentRun {
  ended_at?: EndedAt;
  id: Id5;
  owner_id?: OwnerId5;
  plugin_id: PluginId;
  started_at: StartedAt;
  status: Status1;
  trigger_kind: TriggerKind;
  trigger_metadata?: TriggerMetadata;
  workspace_id?: WorkspaceId5;
}
export interface TriggerMetadata {}
/**
 * An agent's declared identity. Loaded from the plugin manifest.
 *
 * Process-level metadata, not user data — does not extend
 * :class:`WithOwnership`.
 */
export interface AgentSpec {
  capabilities: Capabilities;
  description: Description;
  name: Name;
  plugin_id: PluginId1;
  triggers: Triggers;
  version: Version;
}
/**
 * A point or range marker on a chart — anomaly, intervention, event.
 */
export interface Annotation {
  at: At;
  color?: Color;
  end?: End;
  kind: Kind2;
  text: Text;
}
/**
 * Declarative chart spec — what to render, not how.
 *
 * The web app maps this to whichever chart library is current
 * (Recharts/ECharts/Tremor); swapping the library is a ``apps/web``
 * job, not a contract change.
 */
export interface ChartSpec {
  aggregation?: Aggregation;
  annotations_enabled?: AnnotationsEnabled;
  chart_kind: ChartKind;
  metric: Metric;
  range_days?: RangeDays;
}
/**
 * One assertion inside a narrative, with optional evidence + uncertainty.
 */
export interface Claim {
  evidence?: Evidence;
  text: Text1;
  uncertainty?: Uncertainty | null;
}
/**
 * A pointer to a piece of evidence backing a claim.
 */
export interface EvidenceRef {
  kind: Kind3;
  ref: Ref;
}
/**
 * How sure the narrator is about a claim.
 */
export interface Uncertainty {
  confidence: Confidence;
  reason?: Reason;
}
/**
 * A physical or logical device emitting samples for a Source.
 */
export interface Device {
  hardware_id?: HardwareId;
  id: Id6;
  model?: Model;
  name: Name1;
  owner_id?: OwnerId6;
  source_id: SourceId;
  workspace_id?: WorkspaceId6;
}
/**
 * One error captured during an IngestionRun. Append-only.
 */
export interface IngestionError {
  error_kind: ErrorKind;
  id: Id7;
  message: Message;
  occurred_at: OccurredAt;
  owner_id?: OwnerId7;
  payload_ref?: PayloadRef;
  run_id: RunId3;
  workspace_id?: WorkspaceId7;
}
/**
 * One execution of a Source plugin pulling/receiving data.
 */
export interface IngestionRun {
  ended_at?: EndedAt1;
  errors_count?: ErrorsCount;
  id: Id8;
  measurements_count?: MeasurementsCount;
  owner_id?: OwnerId8;
  source_id: SourceId1;
  started_at: StartedAt1;
  status: Status2;
  workspace_id?: WorkspaceId8;
}
/**
 * A structured observation about the user's data.
 *
 * Severity matches the existing ``analysis.types.Severity`` literal so
 * the v1 statistical engine output round-trips cleanly into v2 narratives.
 */
export interface Insight {
  claims?: Claims;
  metric?: Metric1;
  severity?: Severity;
  summary: Summary;
}
/**
 * The canonical health measurement.
 *
 * Time-instant samples set ``interval_start == interval_end``.
 * Time-interval samples (sleep stages, workouts, ECG) set both.
 */
export interface Measurement {
  confidence?: Confidence1;
  device_id?: DeviceId;
  id?: Id9;
  interval_end: IntervalEnd;
  interval_start: IntervalStart;
  metric: Metric2;
  normalization_version?: NormalizationVersion;
  owner_id?: OwnerId9;
  provenance: Provenance;
  source_id: SourceId2;
  unit: Unit;
  value: Value;
  workspace_id?: WorkspaceId9;
}
/**
 * Always-attached "where did this come from" capsule.
 *
 * ``raw_payload_ref`` is opaque — typically a row id in
 * ``raw_ingestion_log`` so a future replay can reach the exact
 * bytes. Storage detail intentionally lives on the other side of
 * the storage port.
 */
export interface Provenance {
  captured_at: CapturedAt;
  raw_payload_ref?: RawPayloadRef;
  sdk_version: SdkVersion;
  source_plugin_id: SourcePluginId;
}
/**
 * A streamable narrative — daily briefing, weekly summary, etc.
 *
 * The wire shape is the *persisted* form. Streaming chunks go over
 * SSE during render; once complete, the whole artifact is one row
 * in this shape. The dashboard's ``BriefingCard`` reads this.
 */
export interface NarrativeArtifact {
  id: Id10;
  insights?: Insights;
  kind: Kind4;
  narrator_plugin_id: NarratorPluginId;
  narrator_version: NarratorVersion;
  owner_id?: OwnerId10;
  rendered_at: RenderedAt;
  suggested_actions?: SuggestedActions;
  text: Text3;
  workspace_id?: WorkspaceId10;
}
/**
 * A user-visible suggestion. Defaults to requiring approval —
 * suggestions are advisory, not auto-actuated.
 */
export interface SuggestedAction {
  rationale?: Rationale2;
  requires_approval?: RequiresApproval;
  text: Text2;
}
/**
 * A composed UI card — chart + briefing inline.
 *
 * The load-bearing primitive of the agent-platform UX: chart and
 * its narrative ship in one HTTP/SSE response, not two requests.
 */
export interface NarrativeCard {
  chart: ChartSpec;
  narrative?: NarrativeArtifact | null;
  series?: SeriesResponse | null;
}
/**
 * Time-series data for a chart, plus annotations.
 *
 * ``points`` is ``(timestamp, value)`` pairs — typed as a list of
 * two-element tuples so the TS codegen produces a sensible
 * ``[string, number][]`` rather than an opaque object.
 */
export interface SeriesResponse {
  annotations?: Annotations;
  metric: Metric3;
  owner_id?: OwnerId11;
  points: Points;
  unit: Unit1;
  workspace_id?: WorkspaceId11;
}
/**
 * One canonical sample after a Source plugin has parsed it.
 *
 * Wraps a :class:`Measurement` and pins the raw payload it derives
 * from. The split lets us evolve normalization independently of the
 * canonical wire shape.
 */
export interface NormalizedMeasurement {
  measurement: Measurement;
  owner_id?: OwnerId12;
  raw_payload_id: RawPayloadId;
  workspace_id?: WorkspaceId12;
}
/**
 * What the agent observed during a run. Append-only.
 *
 * Findings are intentionally a free-form ``dict`` to keep the
 * contract stable across narrators evolving their statistical
 * output shape.
 */
export interface Observation {
  captured_at: CapturedAt1;
  findings: Findings;
  id: Id11;
  metric?: Metric4;
  owner_id?: OwnerId13;
  run_id: RunId4;
  workspace_id?: WorkspaceId13;
}
export interface Findings {}
/**
 * A capability a plugin declares it needs.
 *
 * Capabilities use the ``read:<scope>`` / ``write:<scope>`` form
 * (e.g. ``read:hrv``, ``write:notifications``) so the policy layer
 * can match on prefix.
 */
export interface PluginCapability {
  description?: Description1;
  name: Name2;
}
/**
 * Every plugin's plugin.yaml validates against this.
 *
 * ``sdk_version`` is the SDK version range the plugin targets
 * (semver, e.g. ``">=0.1,<0.2"``). The loader rejects plugins
 * whose declared range doesn't include the running core SDK.
 * Adding this from day one means we can evolve the SDK contract
 * without silently breaking community plugins.
 */
export interface PluginManifest {
  config_schema?: ConfigSchema;
  consumes?: Consumes;
  emits?: Emits;
  entrypoint: Entrypoint;
  id: Id12;
  kind: Kind5;
  language?: Language;
  name: Name3;
  permissions?: PluginPermissions;
  requires?: Requires;
  sdk_version: SdkVersion1;
  version: Version1;
}
/**
 * Runtime permissions a plugin requests.
 */
export interface PluginPermissions {
  capabilities?: Capabilities1;
  network?: Network;
  secrets?: Secrets;
}
/**
 * Runtime permissions a plugin requests.
 */
export interface PluginPermissions1 {
  capabilities?: Capabilities1;
  network?: Network;
  secrets?: Secrets;
}
/**
 * A payload as the source plugin received it, pre-normalization.
 *
 * Persisted before parsing so we can replay against new normalization
 * code without re-fetching. ``payload_hash`` is sha256 of the canonical
 * JSON form for dedup + idempotency.
 */
export interface RawSourcePayload {
  id: Id13;
  owner_id?: OwnerId14;
  payload: Payload3;
  payload_hash: PayloadHash;
  received_at: ReceivedAt;
  source_id: SourceId3;
  workspace_id?: WorkspaceId14;
}
export interface Payload3 {}
/**
 * A source of health data — Apple HealthKit, Oura, manual log, etc.
 */
export interface Source {
  display_name: DisplayName;
  id: Id14;
  kind: Kind6;
  owner_id?: OwnerId15;
  plugin_id: PluginId2;
  workspace_id?: WorkspaceId15;
}
/**
 * What a Source plugin claims it can produce.
 *
 * Declared in the plugin manifest; used by the ingestion runtime
 * for scheduling and by the dashboard for "available sources" UI.
 */
export interface SourceCapability {
  auth_required?: AuthRequired;
  delivery: Delivery;
  metrics: Metrics;
  plugin_id: PluginId3;
  rate_limit_per_minute?: RateLimitPerMinute;
}
