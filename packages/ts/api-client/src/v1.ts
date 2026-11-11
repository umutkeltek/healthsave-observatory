/**
 * AUTO-GENERATED — do not edit.
 *
 * Regenerate via:
 *   make regen-ts-client
 *
 * Source of truth:
 *   contracts/openapi/v1.locked.json
 */
export interface paths {
    "/api/apple/batch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Apple Batch
         * @description Receive a metric batch from HealthSave iOS app.
         *
         *     Expected payload:
         *     {
         *         "metric": "heart_rate",
         *         "batch_index": 0,
         *         "total_batches": 1,
         *         "samples": [
         *             {"date": "2024-01-15T10:30:00Z", "qty": 72, "source": "Apple Watch"},
         *             ...
         *         ]
         *     }
         */
        post: operations["apple_batch_api_apple_batch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/apple/coverage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Apple Coverage
         * @description Per-metric latest sample timestamp, for iOS backfill-recovery reconciliation.
         */
        get: operations["apple_coverage_api_apple_coverage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/apple/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Apple Status
         * @description Return record counts so the iOS app knows what's synced.
         */
        get: operations["apple_status_api_apple_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Api Health */
        get: operations["api_health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/insights/anomalies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Insights Anomalies
         * @description Return recent anomaly findings from the analysis engine.
         *
         *     Reads ``analysis_findings`` where ``finding_type='anomaly'``, ordered
         *     by ``created_at DESC``. Optional ``since`` limits rows to those
         *     created at-or-after the timestamp. Optional ``severity`` is a
         *     comma-separated list (``info,watch,alert``) matched against the
         *     finding's severity column. SQL lives in
         *     ``storage.timescale.briefings`` — this handler does parameter
         *     validation and wire-shape mapping only.
         */
        get: operations["insights_anomalies_api_insights_anomalies_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/insights/daily": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Insights Daily
         * @description Return today's daily briefing narrative.
         */
        get: operations["insights_daily_api_insights_daily_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/insights/latest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Insights Latest
         * @description Return the most recent daily briefing + weekly summary narratives.
         */
        get: operations["insights_latest_api_insights_latest_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/insights/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Insights Runs
         * @description Recent rows from the pipeline_runs ledger.
         *
         *     The ledger is written by the ``apps/worker`` APScheduler listener
         *     (Phase 4B). This route is the read-side surface — newest first,
         *     optional ``job_kind`` filter, capped at 200 per request.
         *
         *     Status values: pending, running, succeeded, failed, cancelled,
         *     skipped. ``triggered_by`` is one of: scheduler, manual, api, event.
         */
        get: operations["insights_runs_api_insights_runs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/insights/trends": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Insights Trends
         * @description Return recent trend findings from the analysis engine.
         *
         *     SQL lives in ``storage.timescale.briefings`` — this handler does
         *     parameter validation (period format) and wire-shape mapping only.
         */
        get: operations["insights_trends_api_insights_trends_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/insights/trigger": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Insights Trigger
         * @description Run an ad-hoc analysis job inline.
         *
         *     ``daily_briefing`` and ``trend_analysis`` run synchronously against
         *     ``app.state.analysis_engine``. Future long-running job types
         *     (weekly, correlation, etc.) should dispatch to the ``apps/worker``
         *     service via a Postgres NOTIFY queue rather than running inline —
         *     the API process no longer carries a scheduler in v2.
         */
        post: operations["insights_trigger_api_insights_trigger_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/insights/weekly": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Insights Weekly
         * @description Return the current week's summary narrative.
         */
        get: operations["insights_weekly_api_insights_weekly_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/agents/proposals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Proposals
         * @description List recent proposals.
         *
         *     Reads through the agent repository. Per the Phase 5 storage-zone rule, the
         *     route never composes its own query against ``action_proposals``.
         */
        get: operations["list_proposals_api_v2_agents_proposals_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/agents/proposals/{proposal_id}/decide": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Decide Proposal
         * @description Record the operator's decision on one proposal.
         *
         *     Writes a single row into ``action_decisions`` via
         *     :class:`storage.ports.AgentRepository`. The decision is append-only —
         *     re-deciding (e.g. flipping a rejection to an
         *     approval) writes a new row, and downstream readers take the
         *     newest. The supervisor / executor path that picks up an approved
         *     proposal is Phase 7-F territory; Phase 7-E only persists the
         *     decision.
         *
         *     Errors:
         *
         *       * ``404`` — no proposal with that id. We intentionally don't
         *         leak whether the id is malformed-but-syntactically-valid vs.
         *         truly absent; both surface as 404.
         */
        post: operations["decide_proposal_api_v2_agents_proposals__proposal_id__decide_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/apple/batch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * V2 Apple Batch
         * @description Receive a v2 Apple HealthKit batch.
         *
         *     Wire contract: ``POST /api/v2/apple/batch`` with ``schema_version=2``.
         *     Accepts the same idempotency / receipt headers as v1 plus an optional
         *     ``X-HealthSave-Schema-Version: 2`` (advisory — the body schema_version
         *     is the source of truth).
         *
         *     Response: same delivery-receipt shape as v1 with an additive
         *     ``wire_schema_version: 2`` and a ``deletions`` block carrying the
         *     per-table supersede counts.
         */
        post: operations["v2_apple_batch_api_v2_apple_batch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/changes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Changes
         * @description Latest-activity fingerprint with ETag/304 semantics.
         */
        get: operations["changes_api_v2_changes_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/device-identity-links": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Device Identity Link */
        post: operations["create_device_identity_link_api_v2_device_identity_links_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/device-identity-links/session-reconciliations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reconcile Device Identity Link Sessions */
        post: operations["reconcile_device_identity_link_sessions_api_v2_device_identity_links_session_reconciliations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/devices": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Devices */
        get: operations["list_devices_api_v2_devices_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/experiments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Experiments
         * @description List experiments, newest first; optional ``?status=`` filter.
         */
        get: operations["list_experiments_api_v2_experiments_get"];
        put?: never;
        /**
         * Create Experiment
         * @description Create an experiment from a testable candidate.
         *
         *     Validates the pair with the pure readiness classifier: the pair must be
         *     ``testable`` *and* the supplied ``lever_metric_id`` must actually be the
         *     controllable lever (not the outcome). On success the experiment is created
         *     and an immediate retrospective (observational) preview is computed over
         *     existing history — best-effort, so a thin-history install still creates the
         *     experiment cleanly.
         */
        post: operations["create_experiment_api_v2_experiments_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/experiments/candidates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Candidates
         * @description Ranked correlation candidates annotated with experiment readiness.
         *
         *     Strongest correlations first — the top of the list is the best candidate to
         *     promote into an experiment. Deduped to one row per metric pair (the strongest
         *     seen), since the same pair recurs across correlation runs.
         */
        get: operations["list_candidates_api_v2_experiments_candidates_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/experiments/{experiment_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Experiment
         * @description One experiment: definition + phase calendar + progress + latest results.
         */
        get: operations["get_experiment_api_v2_experiments__experiment_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/experiments/{experiment_id}/abandon": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Abandon Experiment
         * @description Stop an experiment (status → abandoned).
         */
        post: operations["abandon_experiment_api_v2_experiments__experiment_id__abandon_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/experiments/{experiment_id}/analyze": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Analyze Experiment
         * @description (Re)compute the controlled ABAB result now and return the refreshed view.
         *
         *     Completes the experiment automatically once its window has fully elapsed.
         */
        post: operations["analyze_experiment_api_v2_experiments__experiment_id__analyze_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Export Data */
        get: operations["export_data_api_v2_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/export/metrics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Export Metrics */
        get: operations["list_export_metrics_api_v2_export_metrics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/insights/correlations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Correlations
         * @description Persisted cross-metric correlation findings, newest first.
         */
        get: operations["list_correlations_api_v2_insights_correlations_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/insights/findings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Findings
         * @description Recent structured findings (the evidence feed), newest first.
         *
         *     Each row carries its ``structured_data`` so the evidence card can show the
         *     calculation behind a finding (effect size, window, p-value, …). Optional
         *     ``?type=`` narrows to one kind.
         */
        get: operations["list_findings_api_v2_insights_findings_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/insights/latest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Latest Narratives
         * @description Most recent daily-briefing + weekly-summary narratives (the weekly-brief card).
         *
         *     ``runs`` carries the latest ``analysis_runs`` attempt per narrator job —
         *     {status, error, at, completed_at, provider} — so the card can distinguish
         *     "no briefing yet" from "the last attempt failed" (silent-failure review).
         */
        get: operations["latest_narratives_api_v2_insights_latest_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/insights/narratives": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Narratives
         * @description Narrative history, newest first — the brief card's "previous briefs".
         */
        get: operations["list_narratives_api_v2_insights_narratives_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/insights/trigger": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Trigger
         * @description Run an analysis job on demand.
         *
         *     Supports ``correlation_analysis``, ``recovery_check``, ``daily_briefing``
         *     and ``weekly_summary`` (the brief card's refresh — Brain-1 findings plus
         *     a Brain-2 narration). Each checks its config block is enabled, runs the
         *     engine job inline through the pipeline_runs ledger, and reports
         *     completed vs skipped.
         */
        post: operations["trigger_api_v2_insights_trigger_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/intelligence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Intelligence
         * @description Current narrator posture (no secrets).
         */
        get: operations["get_intelligence_api_v2_intelligence_get"];
        /**
         * Put Intelligence
         * @description Apply mode + primary + fallback. Does NOT grant cloud egress (see consent).
         */
        put: operations["put_intelligence_api_v2_intelligence_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/intelligence/consent": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Post Consent
         * @description Grant / revoke the cloud-egress opt-in (the separate consent step, D5).
         */
        post: operations["post_consent_api_v2_intelligence_consent_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/intelligence/detect-local": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Detect Local
         * @description Probe the known local Ollama endpoints so the UI can auto-fill "Local".
         *
         *     Returns each candidate's reachability + installed models. No DB, no health
         *     data, no egress (the targets are inside the trust boundary). Lets a
         *     non-technical user click "Detect" instead of typing a base URL.
         */
        get: operations["detect_local_api_v2_intelligence_detect_local_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/intelligence/test-connection": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Test Connection
         * @description Probe a provider (SSRF-guarded, one token, no health data); audit it.
         */
        post: operations["test_connection_api_v2_intelligence_test_connection_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/lab-imports": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Index */
        get: operations["index_api_v2_lab_imports_get"];
        put?: never;
        /** Upload */
        post: operations["upload_api_v2_lab_imports_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/lab-imports/catalog": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Catalog */
        get: operations["catalog_api_v2_lab_imports_catalog_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/lab-imports/{document_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Draft */
        get: operations["draft_api_v2_lab_imports__document_id__get"];
        put?: never;
        post?: never;
        /** Delete Document */
        delete: operations["delete_document_api_v2_lab_imports__document_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/lab-imports/{document_id}/commit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Commit */
        post: operations["commit_api_v2_lab_imports__document_id__commit_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/lab-imports/{document_id}/deletion": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Deletion Preview */
        get: operations["deletion_preview_api_v2_lab_imports__document_id__deletion_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/lab-imports/{document_id}/original": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Original */
        get: operations["original_api_v2_lab_imports__document_id__original_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/lab-imports/{document_id}/report": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Report */
        get: operations["report_api_v2_lab_imports__document_id__report_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/labs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Labs
         * @description Every marker with its results, newest marker first, plus the labs.
         */
        get: operations["list_labs_api_v2_labs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/labs/{loinc}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Lab Marker
         * @description One marker's results, oldest first, each with its lab and the lab's range.
         */
        get: operations["get_lab_marker_api_v2_labs__loinc__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/meta": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * V2 Meta
         * @description Return the v2 version axes. Unauthenticated, read-only, no health data.
         */
        get: operations["v2_meta_api_v2_meta_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/metrics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Metrics
         * @description The full canonical metric catalog (ontology-driven, no DB hit).
         */
        get: operations["list_metrics_api_v2_metrics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/metrics/{metric_id}/series": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Metric Series
         * @description One metric's time-series over a multi-timescale window.
         *
         *     ``stream_id`` optionally narrows the series to a single device stream
         *     (one physical emitter); omitted returns the fused series across all
         *     streams, unchanged.
         */
        get: operations["metric_series_api_v2_metrics__metric_id__series_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/moments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Moments */
        get: operations["list_moments_api_v2_moments_get"];
        put?: never;
        /** Create Moment */
        post: operations["create_moment_api_v2_moments_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/moments/{moment_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Moment */
        put: operations["update_moment_api_v2_moments__moment_id__put"];
        post?: never;
        /** Delete Moment */
        delete: operations["delete_moment_api_v2_moments__moment_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/owners": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Owners
         * @description The default owner first (``label`` null), then one entry per participant.
         *
         *     A participant whose keys are all revoked stays listed with
         *     ``active: false``: revoking a key stops new data, it does not delete the
         *     person's history.
         */
        get: operations["owners_api_v2_owners_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/privacy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Privacy
         * @description The host's egress posture: provider, local-vs-cloud, and what may leave.
         *
         *     ``raw_observations_leave_host`` is always ``false`` — the privacy promise is
         *     an invariant, enforced unconditionally by the policy regardless of opt-in.
         */
        get: operations["privacy_api_v2_privacy_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/readiness": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Readiness
         * @description Per-metric coverage + analyzability, plus source attribution and freshness.
         */
        get: operations["readiness_api_v2_readiness_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/receipts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Receipts
         * @description Egress-relevant audit events (newest first) + ingest freshness.
         */
        get: operations["list_receipts_api_v2_receipts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/series": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Metric Series Batch
         * @description Many metrics' time-series in one request (the dashboard's grid fetch).
         *
         *     ``ids`` is a comma-separated list of metric ids. Unknown ids come back as
         *     per-item ``{"metric_id", "error"}`` entries instead of failing the whole
         *     request, so one bad id can't blank a dashboard. Each known item carries
         *     the exact shape of ``/metrics/{id}/series`` minus the redundant
         *     range/start/end (hoisted to the envelope).
         */
        get: operations["metric_series_batch_api_v2_series_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/settings/analytical-time": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Analytical Time */
        get: operations["get_analytical_time_api_v2_settings_analytical_time_get"];
        /** Update Analytical Time */
        put: operations["update_analytical_time_api_v2_settings_analytical_time_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/setup/diagnostics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Setup Diagnostics
         * @description Return a no-secret setup fingerprint for humans and clients.
         *
         *     This is intentionally unauthenticated: it exposes no health data and helps
         *     users distinguish the Data Hub API from nearby Grafana/Homepage ports before
         *     they troubleshoot keys or sync.
         */
        get: operations["setup_diagnostics_api_v2_setup_diagnostics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/sources": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Sources */
        get: operations["list_sources_api_v2_sources_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/sources/whoop/webhook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Whoop Webhook */
        post: operations["whoop_webhook_api_v2_sources_whoop_webhook_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/streams": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Streams */
        get: operations["list_streams_api_v2_streams_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/streams/{stream_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Stream */
        get: operations["get_stream_api_v2_streams__stream_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/sync/anomalies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Sync Anomalies
         * @description Detect suspicious sync behavior visible from server receipts.
         */
        get: operations["sync_anomalies_api_v2_sync_anomalies_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/sync/coverage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Sync Coverage
         * @description Return metric-level receipt and destination sample coverage.
         */
        get: operations["sync_coverage_api_v2_sync_coverage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/sync/runs/latest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Latest Sync Run
         * @description Summarize the most recently observed HealthSave sync run.
         */
        get: operations["latest_sync_run_api_v2_sync_runs_latest_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/sync/runs/{sync_run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Sync Run
         * @description Return the delivery receipt summary for one HealthSave sync run.
         */
        get: operations["sync_run_api_v2_sync_runs__sync_run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/sync/runs/{sync_run_id}/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Put Sync Run Summary
         * @description Record (or replace) the client's closing summary for one sync run.
         *
         *     Optional for third-party servers, like every ``/api/v2/sync/*`` route: a
         *     client treats 404/405 here as "not supported" and carries on. When present,
         *     it is what lets ``GET /api/v2/sync/runs/latest`` report a run that sent
         *     nothing as the latest run instead of silently repeating the previous one.
         */
        put: operations["put_sync_run_summary_api_v2_sync_runs__sync_run_id__summary_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v2/year/{year}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Year In Health
         * @description One year of the record: months, sources, device changes, every gap.
         */
        get: operations["year_in_health_api_v2_year__year__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health Check */
        get: operations["health_check_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/metrics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Prometheus Metrics */
        get: operations["prometheus_metrics_metrics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Readiness Check */
        get: operations["readiness_check_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AnalyticalTimeView */
        AnalyticalTimeView: {
            /** Day Boundary */
            day_boundary: string;
            /** Day Boundary Minutes */
            day_boundary_minutes: number;
            /** Revision */
            revision: number;
            /**
             * Sleep Day Assignment
             * @default wake_time
             */
            sleep_day_assignment: string;
            /** Time Zone */
            time_zone: string;
        };
        /** AnomaliesListResponse */
        AnomaliesListResponse: {
            /** Anomalies */
            anomalies?: components["schemas"]["AnomalyResponse"][];
            /**
             * Count
             * @default 0
             */
            count: number;
        };
        /** AnomalyResponse */
        AnomalyResponse: {
            /** Context */
            context?: Record<string, never> | null;
            /** Detected At */
            detected_at?: string | null;
            /** Direction */
            direction?: string | null;
            /** Id */
            id?: number | null;
            /** Magnitude */
            magnitude?: number | null;
            /** Metric */
            metric?: string | null;
            /** Severity */
            severity?: string | null;
        };
        /** ApplyIntelligenceRequest */
        ApplyIntelligenceRequest: {
            /** Fallback */
            fallback?: components["schemas"]["ConnectionInput"][] | null;
            /**
             * Mode
             * @enum {string}
             */
            mode: "off" | "local" | "cloud";
            primary?: components["schemas"]["PrimaryInput"] | null;
            /** Redact Cloud Prompts */
            redact_cloud_prompts?: boolean | null;
        };
        /**
         * Confounder
         * @description A competing explanation the engine already accounts for or flags.
         *
         *     Mirrors the context-suppression rules in the detectors (workout-window HR
         *     spikes, post-workout HRV drops, the sleep window) so a card can say *why* a
         *     reading might not mean what it looks like.
         */
        Confounder: {
            /** Description */
            description: string;
            /** Kind */
            kind: string;
            /** Metric */
            metric?: string | null;
        };
        /** ConnectionInput */
        ConnectionInput: {
            /** Api Key */
            api_key?: string | null;
            /** Base Url */
            base_url?: string | null;
            /** Display Name */
            display_name?: string | null;
            /** Model */
            model: string;
            /** Provider */
            provider: string;
        };
        /** ConsentRequest */
        ConsentRequest: {
            /** Consent Text Hash */
            consent_text_hash?: string | null;
            /** Consent Version */
            consent_version?: string | null;
            /** Granted */
            granted: boolean;
        };
        /**
         * Coverage
         * @description Data sufficiency behind the finding — the ``gates.py`` verdict, surfaced.
         *
         *     A finding is only emitted once its producer's sufficiency gate passed, so
         *     ``is_sufficient`` is typically ``True``; ``note`` records the threshold that
         *     was cleared (e.g. "≥14 observations over ≥7 days"). ``days_until_sufficient``
         *     is only meaningful on the not-yet-analyzable path a future producer might
         *     surface.
         */
        Coverage: {
            /** Days Until Sufficient */
            days_until_sufficient?: number | null;
            /** Days With Data */
            days_with_data?: number | null;
            /** Is Sufficient */
            is_sufficient?: boolean | null;
            /** Note */
            note?: string | null;
            /** Observation Count */
            observation_count?: number | null;
        };
        /** CreateExperimentRequest */
        CreateExperimentRequest: {
            /**
             * Block Days
             * @default 7
             */
            block_days: number;
            /**
             * Design
             * @default ABAB
             */
            design: string;
            /** Hypothesis */
            hypothesis?: string | null;
            /** Lever Metric Id */
            lever_metric_id: string;
            /** Outcome Metric Id */
            outcome_metric_id: string;
            /** Start Date */
            start_date?: string | null;
        };
        /** CreateMomentRequest */
        CreateMomentRequest: {
            /** End At */
            end_at?: string | null;
            /** Grade */
            grade?: string | null;
            /** Kind */
            kind: string;
            /** Note */
            note?: string | null;
            /**
             * Start At
             * Format: date-time
             */
            start_at: string;
            /** Title */
            title: string;
        };
        /** DailyBriefingResponse */
        DailyBriefingResponse: {
            /** Created At */
            created_at?: string | null;
            /** Date */
            date?: string | null;
            /** Findings */
            findings?: components["schemas"]["FindingResponse"][];
            /** Id */
            id?: number | null;
            /** Narrative */
            narrative?: string | null;
        };
        /**
         * DecideRequest
         * @description Operator's decision on one proposal.
         *
         *     ``rationale`` is optional but encouraged — Phase 7-E's audit trail
         *     is the same ledger that Phase 7-A laid down; an unexplained
         *     rejection is a near-future regret. The UI should default-prompt.
         */
        DecideRequest: {
            /**
             * Decision
             * @enum {string}
             */
            decision: "approved" | "rejected" | "deferred";
            /** Rationale */
            rationale?: string | null;
        };
        /** DecideResponse */
        DecideResponse: {
            /**
             * Decided By
             * @enum {string}
             */
            decided_by: "user" | "policy" | "auto";
            /**
             * Decision
             * @enum {string}
             */
            decision: "approved" | "rejected" | "deferred";
            /**
             * Decision Id
             * Format: uuid
             */
            decision_id: string;
            /**
             * Proposal Id
             * Format: uuid
             */
            proposal_id: string;
        };
        /**
         * Delta
         * @description The change: current vs baseline.
         */
        Delta: {
            /** Absolute */
            absolute?: number | null;
            /** Direction */
            direction?: ("up" | "down" | "flat") | null;
            /** Pct */
            pct?: number | null;
            /** Unit */
            unit?: string | null;
        };
        /** DeviceIdentityLinkCreate */
        DeviceIdentityLinkCreate: {
            /**
             * Confidence
             * @default strong
             * @enum {string}
             */
            confidence: "medium" | "strong";
            /**
             * Direct Stream Id
             * Format: uuid
             */
            direct_stream_id: string;
            /** Evidence */
            evidence?: Record<string, never>;
            /**
             * Relayed Stream Id
             * Format: uuid
             */
            relayed_stream_id: string;
            /**
             * Status
             * @default confirmed
             * @constant
             * @enum {string}
             */
            status: "confirmed";
        };
        /** DeviceIdentityLinkResponse */
        DeviceIdentityLinkResponse: {
            /**
             * Confidence
             * @enum {string}
             */
            confidence: "medium" | "strong";
            /**
             * Direct Stream Id
             * Format: uuid
             */
            direct_stream_id: string;
            /**
             * Relayed Stream Id
             * Format: uuid
             */
            relayed_stream_id: string;
            /**
             * Status
             * @constant
             * @enum {string}
             */
            status: "confirmed";
        };
        /** DeviceView */
        DeviceView: {
            /** Device Label */
            device_label?: string | null;
            /**
             * First Seen At
             * Format: date-time
             */
            first_seen_at: string;
            /**
             * Last Seen At
             * Format: date-time
             */
            last_seen_at: string;
            /** Stream Count */
            stream_count: number;
        };
        /** DevicesResponse */
        DevicesResponse: {
            /** Count */
            count: number;
            /** Devices */
            devices: components["schemas"]["DeviceView"][];
            /** Total */
            total?: number | null;
        };
        /**
         * EffectSize
         * @description How big the effect is, method-tagged so the UI can label it honestly.
         *
         *     ``kind`` names the statistic (``z_score`` / ``spearman_rho`` /
         *     ``slope_per_day`` / ``cohens_d`` …) so a reader never confuses a correlation
         *     coefficient with a standardized mean difference. ``p_value`` rides alongside
         *     the magnitude (significance ≠ size) rather than being a separate top-level
         *     card field.
         */
        EffectSize: {
            /** Kind */
            kind?: string | null;
            /** Label */
            label?: string | null;
            /** P Value */
            p_value?: number | null;
            /** Value */
            value?: number | null;
        };
        /**
         * ExperimentCandidateRef
         * @description Machine hook linking ``next_question`` to the experiments surface.
         *
         *     Deliberately speaks the ``/api/v2/experiments/candidates`` vocabulary
         *     (metric pair + lever/outcome/verdict/protocol from the readiness classifier)
         *     — the candidate shape the experiment engine already ranks, so nothing new is
         *     invented here. The ``POST /api/v2/experiments`` create body renames the pair
         *     to ``lever_metric_id`` / ``outcome_metric_id``: the values are identical, only
         *     the field names differ, so the client maps ``lever`` → ``lever_metric_id`` and
         *     ``outcome`` → ``outcome_metric_id`` when promoting a candidate.
         */
        ExperimentCandidateRef: {
            /** Lever */
            lever?: string | null;
            /** Metric A */
            metric_a: string;
            /** Metric B */
            metric_b: string;
            /** Outcome */
            outcome?: string | null;
            /** Required Days */
            required_days?: number | null;
            /** Suggested Protocol */
            suggested_protocol?: string | null;
            /** Verdict */
            verdict?: string | null;
        };
        /** ExperimentListResponse */
        ExperimentListResponse: {
            /** Count */
            count: number;
            /** Experiments */
            experiments: components["schemas"]["ExperimentView"][];
        };
        /** ExperimentView */
        ExperimentView: {
            /** Block Days */
            block_days: number;
            /** Calendar */
            calendar: components["schemas"]["PhaseView"][];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Design */
            design: string;
            /** Hypothesis */
            hypothesis: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Lever */
            lever: string;
            /** Lever Metric Id */
            lever_metric_id: string;
            /** Outcome */
            outcome: string;
            /** Outcome Metric Id */
            outcome_metric_id: string;
            progress: components["schemas"]["ProgressView"];
            /** Results */
            results: {
                [key: string]: components["schemas"]["ResultView"];
            };
            /**
             * Start Date
             * Format: date
             */
            start_date: string;
            /** Status */
            status: string;
        };
        /**
         * FindingCard
         * @description The versioned content model for one evidence-linked finding.
         *
         *     ``claim`` / ``metric`` / ``schema_version`` are required; everything else is
         *     optional so legacy or thin findings are represented without fabrication.
         */
        FindingCard: {
            baseline_window?: components["schemas"]["WindowRef"] | null;
            /** Claim */
            claim: string;
            /** Confidence */
            confidence?: ("low" | "medium" | "high") | null;
            /** Confounders */
            confounders?: components["schemas"]["Confounder"][];
            coverage?: components["schemas"]["Coverage"] | null;
            current_window?: components["schemas"]["WindowRef"] | null;
            delta?: components["schemas"]["Delta"] | null;
            effect_size?: components["schemas"]["EffectSize"] | null;
            /** Finding Type */
            finding_type?: string | null;
            /** Limitations */
            limitations?: string[];
            /** Metric */
            metric: string;
            next_question?: components["schemas"]["NextQuestion"] | null;
            /**
             * Schema Version
             * @default 1
             */
            schema_version: number;
            /** Sources */
            sources?: components["schemas"]["SourceRef"][];
        };
        /** FindingResponse */
        FindingResponse: {
            /** Created At */
            created_at?: string | null;
            /** Finding Type */
            finding_type?: string | null;
            /** Id */
            id?: number | null;
            /** Metric */
            metric?: string | null;
            /** Severity */
            severity?: string | null;
            /** Structured Data */
            structured_data?: Record<string, never> | null;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** InsightsLatestResponse */
        InsightsLatestResponse: {
            daily_briefing?: components["schemas"]["DailyBriefingResponse"] | null;
            /** Recent Findings */
            recent_findings?: components["schemas"]["FindingResponse"][];
            weekly_summary?: components["schemas"]["WeeklySummaryResponse"] | null;
        };
        /** LabAssessmentView */
        LabAssessmentView: {
            /** Change */
            change: number | null;
            /** Change Pct */
            change_pct: number | null;
            /** Change Withheld */
            change_withheld: string | null;
            /** Direction */
            direction: string | null;
            /** Latest Band */
            latest_band: string;
            /** Outside Streak */
            outside_streak: number;
            /** Previous From Other Lab */
            previous_from_other_lab: boolean;
            /** Previous Specimen At */
            previous_specimen_at: string | null;
            /** Prior Count */
            prior_count: number;
            /** Prior Max */
            prior_max: number | null;
            /** Prior Min */
            prior_min: number | null;
            /** Versus History */
            versus_history: string | null;
        };
        /** LabCrossMatchView */
        LabCrossMatchView: {
            card: components["schemas"]["FindingCard"] | null;
            /** Reason */
            reason: string | null;
            /** Related Label */
            related_label: string;
            /** Related Metric Id */
            related_metric_id: string;
            /** Related Unit */
            related_unit: string;
            /** Stream Id */
            stream_id: string | null;
            /** Stream Label */
            stream_label: string | null;
        };
        /** LabDocumentPage */
        LabDocumentPage: {
            /**
             * Method
             * @enum {string}
             */
            method: "text" | "ocr" | "csv";
            /** Page */
            page: number;
            /** Text */
            text: string;
        };
        /** LabEvidenceSource */
        LabEvidenceSource: {
            /** Accessed On */
            accessed_on: string;
            /** Id */
            id: string;
            /** Scope */
            scope: string;
            /** Title */
            title: string;
            /** Url */
            url: string;
        };
        /** LabGapView */
        LabGapView: {
            /** Bands Disagree */
            bands_disagree: boolean;
            /** Days Apart */
            days_apart: number;
            /** Difference */
            difference: number | null;
            /** Difference Pct */
            difference_pct: number | null;
            /** Earlier Band */
            earlier_band: string;
            /**
             * Earlier Id
             * Format: uuid
             */
            earlier_id: string;
            /** Earlier Lab */
            earlier_lab: string;
            /**
             * Earlier Specimen At
             * Format: date-time
             */
            earlier_specimen_at: string;
            /** Earlier Value */
            earlier_value: number;
            /** Later Band */
            later_band: string;
            /**
             * Later Id
             * Format: uuid
             */
            later_id: string;
            /** Later Lab */
            later_lab: string;
            /**
             * Later Specimen At
             * Format: date-time
             */
            later_specimen_at: string;
            /** Later Value */
            later_value: number;
            /** Unit */
            unit: string;
        };
        /** LabImportCatalog */
        LabImportCatalog: {
            /** Markers */
            markers: components["schemas"]["LabImportMarker"][];
        };
        /** LabImportDeletion */
        LabImportDeletion: {
            /**
             * Confirmation
             * Format: uuid
             */
            confirmation: string;
            /**
             * Delete Results
             * @default false
             */
            delete_results: boolean;
            /**
             * Owner Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            owner_id: string;
            /**
             * Workspace Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            workspace_id: string;
        };
        /** LabImportDeletionPreview */
        LabImportDeletionPreview: {
            /**
             * Explanation
             * @default Deletes this original and saved report. Optionally deletes results last written by this import; later corrections and other reports are preserved. Copies in your downloads or backups are separate.
             */
            explanation: string;
            /** File Name */
            file_name: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Linked Result Count */
            linked_result_count: number;
            /**
             * Owner Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            owner_id: string;
            /**
             * Workspace Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            workspace_id: string;
        };
        /** LabImportDeletionReceipt */
        LabImportDeletionReceipt: {
            /** Deleted Results */
            deleted_results: number;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Owner Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            owner_id: string;
            /**
             * Workspace Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            workspace_id: string;
        };
        /** LabImportDraft */
        LabImportDraft: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** File Name */
            file_name: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Owner Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            owner_id: string;
            /** Pages */
            pages: components["schemas"]["LabDocumentPage"][];
            /** Rows */
            rows: components["schemas"]["LabReviewRow"][];
            /** Sha256 */
            sha256: string;
            /**
             * Status
             * @enum {string}
             */
            status: "draft" | "committed";
            /** Warnings */
            warnings: string[];
            /**
             * Workspace Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            workspace_id: string;
        };
        /** LabImportIndex */
        LabImportIndex: {
            /** Documents */
            documents: components["schemas"]["LabImportIndexItem"][];
            /**
             * Owner Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            owner_id: string;
            /**
             * Workspace Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            workspace_id: string;
        };
        /** LabImportIndexItem */
        LabImportIndexItem: {
            /** Committed At */
            committed_at: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** File Name */
            file_name: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Sha256 */
            sha256: string;
        };
        /** LabImportMarker */
        LabImportMarker: {
            /** Loinc */
            loinc: string;
            /** Name */
            name: string;
            /** Unit */
            unit: string;
        };
        /** LabImportReceipt */
        LabImportReceipt: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Inserted */
            inserted: number;
            /**
             * Owner Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            owner_id: string;
            /** Report Url */
            report_url: string;
            /** Result Count */
            result_count: number;
            /** Unchanged */
            unchanged: number;
            /** Updated */
            updated: number;
            /**
             * Workspace Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            workspace_id: string;
        };
        /** LabImportReport */
        LabImportReport: {
            /** File Name */
            file_name: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Imported At
             * Format: date-time
             */
            imported_at: string;
            /** Limitations */
            limitations: string[];
            /**
             * Owner Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            owner_id: string;
            /** Report Version */
            report_version: string;
            /** Results */
            results: components["schemas"]["LabReportResult"][];
            /** Review Status */
            review_status: string;
            /** Sha256 */
            sha256: string;
            /** Sources */
            sources: components["schemas"]["LabEvidenceSource"][];
            /**
             * Workspace Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            workspace_id: string;
        };
        /** LabImportReview */
        LabImportReview: {
            /**
             * Owner Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            owner_id: string;
            /** Rows */
            rows: components["schemas"]["LabReviewRow"][];
            /**
             * Workspace Id
             * Format: uuid
             * @default 00000000-0000-0000-0000-000000000001
             */
            workspace_id: string;
        };
        /** LabMarkerDetail */
        LabMarkerDetail: {
            assessment: components["schemas"]["LabAssessmentView"] | null;
            cross_match: components["schemas"]["LabCrossMatchView"] | null;
            /** Display Unit */
            display_unit: string;
            /**
             * First Specimen At
             * Format: date-time
             */
            first_specimen_at: string;
            /** Gap Count */
            gap_count: number;
            /** Gaps */
            gaps: components["schemas"]["LabGapView"][];
            /** Lab Count */
            lab_count: number;
            /**
             * Last Specimen At
             * Format: date-time
             */
            last_specimen_at: string;
            /** Loinc */
            loinc: string;
            /** Metric Id */
            metric_id: string;
            /** Name */
            name: string;
            /** Related Metric Id */
            related_metric_id: string | null;
            /** Result Count */
            result_count: number;
            /** Results */
            results: components["schemas"]["LabResultView"][];
            /** Unit */
            unit: string;
        };
        /** LabMarkerView */
        LabMarkerView: {
            assessment: components["schemas"]["LabAssessmentView"] | null;
            /** Display Unit */
            display_unit: string;
            /**
             * First Specimen At
             * Format: date-time
             */
            first_specimen_at: string;
            /** Gap Count */
            gap_count: number;
            /** Lab Count */
            lab_count: number;
            /**
             * Last Specimen At
             * Format: date-time
             */
            last_specimen_at: string;
            /** Loinc */
            loinc: string;
            /** Metric Id */
            metric_id: string;
            /** Name */
            name: string;
            /** Related Metric Id */
            related_metric_id: string | null;
            /** Result Count */
            result_count: number;
            /** Results */
            results: components["schemas"]["LabResultView"][];
            /** Unit */
            unit: string;
        };
        /** LabReportComparison */
        LabReportComparison: {
            /** Absolute Change */
            absolute_change: number;
            /**
             * Method
             * @default Most recent earlier result from the same lab, test and normalized unit.
             */
            method: string;
            /** Percent Change */
            percent_change: number | null;
            /**
             * Previous Specimen At
             * Format: date-time
             */
            previous_specimen_at: string;
            /** Previous Value */
            previous_value: number;
        };
        /** LabReportResult */
        LabReportResult: {
            /** Comparator */
            comparator: string | null;
            comparison?: components["schemas"]["LabReportComparison"] | null;
            /** Lab */
            lab: string;
            /** Loinc */
            loinc: string;
            /** Marker */
            marker: string;
            /** Measurement Quality */
            measurement_quality: string;
            /** Medical Evidence */
            medical_evidence: string;
            /** Observation */
            observation: string;
            /** Personal Pattern */
            personal_pattern: string;
            /** Quality Flags */
            quality_flags: string[];
            /** Reference High */
            reference_high: number | null;
            /** Reference Low */
            reference_low: number | null;
            /** Source Excerpt */
            source_excerpt: string | null;
            /** Source Ids */
            source_ids: string[];
            /** Source Page */
            source_page: number | null;
            /**
             * Specimen At
             * Format: date-time
             */
            specimen_at: string;
            /** Unit */
            unit: string;
            /** Value */
            value: number;
        };
        /** LabResultView */
        LabResultView: {
            /** Band */
            band: string;
            /** Band Fraction */
            band_fraction: number | null;
            /** Comparator */
            comparator: string | null;
            /** Date Only */
            date_only: boolean;
            /** Display Unit */
            display_unit: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Lab */
            lab: string;
            /** Panel */
            panel: string | null;
            /** Quality Flags */
            quality_flags: string[];
            /** Reference High */
            reference_high: number | null;
            /** Reference Low */
            reference_low: number | null;
            /** Source Plugin Id */
            source_plugin_id: string;
            /**
             * Specimen At
             * Format: date-time
             */
            specimen_at: string;
            /**
             * Stream Id
             * Format: uuid
             */
            stream_id: string;
            /** Unit */
            unit: string;
            /** Value */
            value: number;
        };
        /** LabReviewRow */
        LabReviewRow: {
            /**
             * Confirmed
             * @default false
             */
            confirmed: boolean;
            /**
             * Lab
             * @default
             */
            lab: string;
            /**
             * Loinc
             * @default
             */
            loinc: string;
            /**
             * Marker Name
             * @default
             */
            marker_name: string;
            /**
             * Panel
             * @default
             */
            panel: string;
            /**
             * Reference High
             * @default
             */
            reference_high: string;
            /**
             * Reference Low
             * @default
             */
            reference_low: string;
            /** Row Id */
            row_id: string;
            /**
             * Specimen Datetime
             * @default
             */
            specimen_datetime: string;
            /**
             * Unit
             * @default
             */
            unit: string;
            /**
             * Value
             * @default
             */
            value: string;
        };
        /** LabSourceView */
        LabSourceView: {
            /**
             * First Specimen At
             * Format: date-time
             */
            first_specimen_at: string;
            /** Lab */
            lab: string;
            /**
             * Last Specimen At
             * Format: date-time
             */
            last_specimen_at: string;
            /** Result Count */
            result_count: number;
            /** Source Plugin Id */
            source_plugin_id: string;
            /**
             * Stream Id
             * Format: uuid
             */
            stream_id: string;
        };
        /** LabsOverview */
        LabsOverview: {
            /** Count */
            count: number;
            /** Labs */
            labs: components["schemas"]["LabSourceView"][];
            /** Markers */
            markers: components["schemas"]["LabMarkerView"][];
            /** Result Count */
            result_count: number;
        };
        /** MomentListResponse */
        MomentListResponse: {
            /** Count */
            count: number;
            /** Moments */
            moments: components["schemas"]["MomentView"][];
        };
        /** MomentView */
        MomentView: {
            /** Created At */
            created_at: string | null;
            /** End At */
            end_at: string | null;
            /** Grade */
            grade: string | null;
            /** Id */
            id: number;
            /** Kind */
            kind: string;
            /** Note */
            note: string | null;
            /**
             * Start At
             * Format: date-time
             */
            start_at: string;
            /** Title */
            title: string;
            /** Updated At */
            updated_at: string | null;
        };
        /**
         * NextQuestion
         * @description The flywheel field: prose + an optional promotable experiment candidate.
         */
        NextQuestion: {
            experiment_candidate?: components["schemas"]["ExperimentCandidateRef"] | null;
            /** Prose */
            prose: string;
        };
        /** OwnerView */
        OwnerView: {
            /** Active */
            active: boolean;
            /** Created At */
            created_at: string | null;
            /** Id */
            id: string;
            /** Is Default */
            is_default: boolean;
            /** Label */
            label: string | null;
            /** Last Ingest At */
            last_ingest_at: string | null;
            /** Scopes */
            scopes: string[];
        };
        /** OwnersResponse */
        OwnersResponse: {
            /** Count */
            count: number;
            /** Owners */
            owners: components["schemas"]["OwnerView"][];
        };
        /** PhaseView */
        PhaseView: {
            /**
             * End
             * Format: date
             */
            end: string;
            /** Index */
            index: number;
            /** Label */
            label: string;
            /**
             * Start
             * Format: date
             */
            start: string;
        };
        /** PrimaryInput */
        PrimaryInput: {
            /** Api Key */
            api_key?: string | null;
            /** Base Url */
            base_url?: string | null;
            /** Display Name */
            display_name?: string | null;
            /** Max Tokens */
            max_tokens?: number | null;
            /** Model */
            model: string;
            /** Provider */
            provider: string;
            /** Temperature */
            temperature?: number | null;
        };
        /** ProgressView */
        ProgressView: {
            /** Current Phase */
            current_phase: string | null;
            /** Day Index */
            day_index: number;
            /** Days Remaining */
            days_remaining: number;
            /** Is Complete */
            is_complete: boolean;
            /** Pct */
            pct: number;
            /** Total Days */
            total_days: number;
        };
        /**
         * ProposalView
         * @description One proposal as it appears on the wire.
         *
         *     Single-user-mode drops ``owner_id`` + ``workspace_id`` — they're
         *     sentinel UUIDs on every row and add noise. Phase 9+ multi-tenant
         *     work re-surfaces them. ``decided`` is a convenience flag so
         *     dashboards can render decision status without joining client-side.
         */
        ProposalView: {
            /**
             * Action Kind
             * @enum {string}
             */
            action_kind: "notify" | "create_experiment" | "create_briefing" | "request_user_input" | "tag_measurement";
            /** Capability */
            capability: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Idempotency Key */
            idempotency_key?: string | null;
            /** Payload */
            payload: Record<string, never>;
            /**
             * Proposed At
             * Format: date-time
             */
            proposed_at: string;
            /** Rationale */
            rationale: string;
            /**
             * Run Id
             * Format: uuid
             */
            run_id: string;
        };
        /** ProposalsListResponse */
        ProposalsListResponse: {
            /** Count */
            count: number;
            /** Proposals */
            proposals: components["schemas"]["ProposalView"][];
            /** Undecided Only */
            undecided_only: boolean;
        };
        /** ResultView */
        ResultView: {
            /** Adherence */
            adherence: Record<string, never> | null;
            /** Caveat */
            caveat: string | null;
            /**
             * Computed At
             * Format: date-time
             */
            computed_at: string;
            /** Diff */
            diff: number | null;
            /** Direction */
            direction: string | null;
            /** Effect Size */
            effect_size: number | null;
            /** Inference */
            inference: string | null;
            /** Kind */
            kind: string;
            /** Mean A */
            mean_a: number | null;
            /** Mean B */
            mean_b: number | null;
            /** N A */
            n_a: number | null;
            /** N B */
            n_b: number | null;
            /** N Blocks Used */
            n_blocks_used: number | null;
            /** P Value */
            p_value: number | null;
            /** Summary */
            summary: string | null;
        };
        /**
         * RunSummaryResponse
         * @description One row from the pipeline_runs ledger as the dashboard sees it.
         */
        RunSummaryResponse: {
            /**
             * Attempt
             * @default 1
             */
            attempt: number;
            /** Ended At */
            ended_at?: string | null;
            /** Error */
            error?: string | null;
            /** Id */
            id: number;
            /** Job Kind */
            job_kind: string;
            /** Started At */
            started_at?: string | null;
            /** Status */
            status: string;
            /**
             * Triggered By
             * @default scheduler
             */
            triggered_by: string;
        };
        /** RunsListResponse */
        RunsListResponse: {
            /**
             * Count
             * @default 0
             */
            count: number;
            /** Runs */
            runs?: components["schemas"]["RunSummaryResponse"][];
        };
        /** SessionFusionReconciliationResponse */
        SessionFusionReconciliationResponse: {
            /** Assigned */
            assigned: number;
            /** Matched Pairs */
            matched_pairs: number;
            /** Rejected */
            rejected: number;
        };
        /**
         * SourceRef
         * @description Where the underlying data came from (provenance, at card granularity).
         */
        SourceRef: {
            /** Label */
            label?: string | null;
            /** Source Plugin Id */
            source_plugin_id?: string | null;
        };
        /** SourceView */
        SourceView: {
            /** Display Name */
            display_name?: string | null;
            /**
             * First Seen At
             * Format: date-time
             */
            first_seen_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Last Seen At
             * Format: date-time
             */
            last_seen_at: string;
            /** Plugin Id */
            plugin_id: string;
        };
        /** SourcesResponse */
        SourcesResponse: {
            /** Count */
            count: number;
            /** Sources */
            sources: components["schemas"]["SourceView"][];
            /** Total */
            total?: number | null;
        };
        /** StreamView */
        StreamView: {
            /** Device Label */
            device_label?: string | null;
            /**
             * First Seen At
             * Format: date-time
             */
            first_seen_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Last Seen At
             * Format: date-time
             */
            last_seen_at: string;
            /** Origin Key */
            origin_key: string;
            /** Source Plugin Id */
            source_plugin_id: string;
        };
        /** StreamsResponse */
        StreamsResponse: {
            /** Count */
            count: number;
            /** Streams */
            streams: components["schemas"]["StreamView"][];
            /** Total */
            total?: number | null;
        };
        /**
         * SyncRunSummaryPayload
         * @description What a HealthSave client says about a run it just closed.
         *
         *     Receipts are written per HTTP batch, so a run that had nothing to send left
         *     no trace on the server and ``GET /api/v2/sync/runs/latest`` kept answering
         *     with the previous run. This body is the run's existence proof: one small
         *     PUT per completed run, idempotent on the run id. It carries counts and
         *     metric NAMES only — never a health value.
         *
         *     ``extra='allow'`` keeps the shape forward-compatible (a newer client may add
         *     keys an older server ignores); the enumerated fields are validated
         *     deterministically and a bad value is a 422, never a 500.
         */
        SyncRunSummaryPayload: {
            /** Client App Version */
            client_app_version?: string | null;
            /** Client Platform */
            client_platform?: string | null;
            /** Completed At */
            completed_at?: string | null;
            /**
             * Delivery
             * @enum {string}
             */
            delivery: "none" | "foreground" | "background_queued";
            /** Error Class */
            error_class?: string | null;
            /** Intent */
            intent?: ("latest_changes" | "backfill" | "date_range") | null;
            /** Metrics Checked */
            metrics_checked?: string[];
            /** Metrics With Changes */
            metrics_with_changes?: string[];
            /**
             * Outcome
             * @enum {string}
             */
            outcome: "completed" | "failed";
            /** Records Sent */
            records_sent: number;
            /**
             * Schema Version
             * @default 1
             * @constant
             * @enum {integer}
             */
            schema_version: 1;
            /** Started At */
            started_at?: string | null;
            /** Trigger */
            trigger?: string | null;
        } & {
            [key: string]: unknown;
        };
        /** TestConnectionRequest */
        TestConnectionRequest: {
            /** Api Key */
            api_key?: string | null;
            /** Base Url */
            base_url?: string | null;
            /** Connection Id */
            connection_id?: number | null;
            /** Model */
            model?: string | null;
            /** Provider */
            provider?: string | null;
        };
        /** TrendResponse */
        TrendResponse: {
            /** Confidence */
            confidence?: string | null;
            /** Direction */
            direction?: string | null;
            /** Metric */
            metric?: string | null;
            /** P Value */
            p_value?: number | null;
            /** Period Days */
            period_days?: number | null;
            /** Slope */
            slope?: number | null;
        };
        /** TrendsListResponse */
        TrendsListResponse: {
            /**
             * Count
             * @default 0
             */
            count: number;
            /** Trends */
            trends?: components["schemas"]["TrendResponse"][];
        };
        /**
         * TriggerBody
         * @description v2 trigger request — extensible by ``type`` (correlation_analysis,
         *     recovery_check, daily_briefing, weekly_summary).
         */
        TriggerBody: {
            /**
             * Type
             * @default correlation_analysis
             */
            type: string;
        };
        /** TriggerRequest */
        TriggerRequest: {
            /**
             * Type
             * @default daily_briefing
             */
            type: string;
        };
        /** TriggerResponse */
        TriggerResponse: {
            /** Message */
            message?: string | null;
            /** Run Id */
            run_id?: number | null;
            /** Run Type */
            run_type?: string | null;
            /**
             * Status
             * @default accepted
             */
            status: string;
        };
        /** UpdateAnalyticalTimeRequest */
        UpdateAnalyticalTimeRequest: {
            /** Day Boundary Minutes */
            day_boundary_minutes: number;
            /** Time Zone */
            time_zone: string;
        };
        /** UpdateMomentRequest */
        UpdateMomentRequest: {
            /** End At */
            end_at?: string | null;
            /** Grade */
            grade?: string | null;
            /** Kind */
            kind: string;
            /** Note */
            note?: string | null;
            /**
             * Start At
             * Format: date-time
             */
            start_at: string;
            /** Title */
            title: string;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /** WeeklySummaryResponse */
        WeeklySummaryResponse: {
            /** Created At */
            created_at?: string | null;
            /** Findings */
            findings?: components["schemas"]["FindingResponse"][];
            /** Id */
            id?: number | null;
            /** Narrative */
            narrative?: string | null;
            /** Week End */
            week_end?: string | null;
            /** Week Start */
            week_start?: string | null;
        };
        /**
         * WindowRef
         * @description A time window a finding is measured over (current or baseline).
         */
        WindowRef: {
            /** End */
            end?: string | null;
            /** Label */
            label?: string | null;
            /** N */
            n?: number | null;
            /** Start */
            start?: string | null;
        };
        /** YearDeviceChangeView */
        YearDeviceChangeView: {
            /**
             * Day
             * Format: date
             */
            day: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "first_seen" | "last_seen";
            /** Label */
            label: string;
            /**
             * Stream Id
             * Format: uuid
             */
            stream_id: string;
        };
        /** YearFamilyView */
        YearFamilyView: {
            /**
             * Confidence
             * @enum {string}
             */
            confidence: "ok" | "low" | "none" | "future";
            /** Days With Data */
            days_with_data: number;
            /** Days Without Data */
            days_without_data: number;
            /** First Day */
            first_day: string | null;
            /** Gaps */
            gaps: components["schemas"]["YearGapView"][];
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** Last Day */
            last_day: string | null;
            /** Longest Inside Gap */
            longest_inside_gap: number;
            /** Mask */
            mask: string;
            /** Metric Ids */
            metric_ids: string[];
        };
        /** YearGapView */
        YearGapView: {
            /** Days */
            days: number;
            /**
             * End
             * Format: date
             */
            end: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "before_first" | "inside" | "after_last" | "no_data";
            /**
             * Start
             * Format: date
             */
            start: string;
        };
        /** YearHeadlineView */
        YearHeadlineView: {
            /** Basis */
            basis: string;
            /**
             * Confidence
             * @enum {string}
             */
            confidence: "ok" | "low" | "none" | "future";
            /** Days */
            days: number | null;
            /** High */
            high: number | null;
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** Low */
            low: number | null;
            /** Of Days */
            of_days: number | null;
            /** Source Label */
            source_label: string | null;
            /** Stream Id */
            stream_id: string | null;
            /** Unit */
            unit: string | null;
            /** Value */
            value: number;
        };
        /** YearInHealth */
        YearInHealth: {
            /**
             * Confidence
             * @enum {string}
             */
            confidence: "ok" | "low" | "none" | "future";
            /** Day Boundary */
            day_boundary: string;
            /** Day Family Counts */
            day_family_counts: number[];
            /** Days In Window */
            days_in_window: number;
            /** Days With Data */
            days_with_data: number;
            /** Device Changes */
            device_changes: components["schemas"]["YearDeviceChangeView"][];
            /** Families */
            families: components["schemas"]["YearFamilyView"][];
            /** First Day */
            first_day: string | null;
            /** Gaps */
            gaps: components["schemas"]["YearGapView"][];
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
            /** Headlines */
            headlines: components["schemas"]["YearHeadlineView"][];
            /** Last Day */
            last_day: string | null;
            /** Limitations */
            limitations: components["schemas"]["YearLimitationView"][];
            /** Longest Inside Gap */
            longest_inside_gap: number;
            /** Mask */
            mask: string;
            /** Months */
            months: components["schemas"]["YearMonthView"][];
            /**
             * Owner Id
             * Format: uuid
             */
            owner_id: string;
            /** Sources */
            sources: components["schemas"]["YearSourceView"][];
            /** Time Zone */
            time_zone: string;
            /**
             * Window End
             * Format: date
             */
            window_end: string;
            /**
             * Window Start
             * Format: date
             */
            window_start: string;
            /** Withheld */
            withheld: components["schemas"]["YearWithheldView"][];
            /** Year */
            year: number;
        };
        /** YearLimitationView */
        YearLimitationView: {
            /** Code */
            code: string;
            /** Count */
            count: number | null;
            /** Day */
            day: string | null;
        };
        /** YearMonthView */
        YearMonthView: {
            /**
             * Confidence
             * @enum {string}
             */
            confidence: "ok" | "low" | "none" | "future";
            /** Coverage */
            coverage: number | null;
            /** Days */
            days: number;
            /** Days With Data */
            days_with_data: number;
            /** Families */
            families: string[];
            /** First Seen Ids */
            first_seen_ids: string[];
            /** Last Seen Ids */
            last_seen_ids: string[];
            /** Month */
            month: number;
            /** Source Ids */
            source_ids: string[];
        };
        /** YearSourceView */
        YearSourceView: {
            /** Days With Data */
            days_with_data: number;
            /** Families */
            families: string[];
            /**
             * First Day
             * Format: date
             */
            first_day: string;
            /** First Seen At */
            first_seen_at: string | null;
            /** Label */
            label: string;
            /**
             * Last Day
             * Format: date
             */
            last_day: string;
            /** Last Seen At */
            last_seen_at: string | null;
            /** Months */
            months: number[];
            /** New This Year */
            new_this_year: boolean;
            /** Source Plugin Id */
            source_plugin_id: string;
            /** Stopped This Year */
            stopped_this_year: boolean;
            /**
             * Stream Id
             * Format: uuid
             */
            stream_id: string;
        };
        /** YearWithheldView */
        YearWithheldView: {
            /** Days */
            days: number;
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** Reason */
            reason: string;
            /** Source Label */
            source_label: string | null;
            /** Stream Id */
            stream_id: string | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    apple_batch_api_apple_batch_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    apple_coverage_api_apple_coverage_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    apple_status_api_apple_status_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    insights_anomalies_api_insights_anomalies_get: {
        parameters: {
            query?: {
                /** @description ISO-8601 lower bound on created_at */
                since?: string | null;
                /** @description Comma-separated list: info, watch, alert */
                severity?: string | null;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnomaliesListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    insights_daily_api_insights_daily_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DailyBriefingResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    insights_latest_api_insights_latest_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InsightsLatestResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    insights_runs_api_insights_runs_get: {
        parameters: {
            query?: {
                /** @description Filter to a specific scheduler job (e.g. 'daily_briefing'). */
                job_kind?: string | null;
                limit?: number;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunsListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    insights_trends_api_insights_trends_get: {
        parameters: {
            query?: {
                /** @description Optional day period filter such as 30d or 90d */
                period?: string | null;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TrendsListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    insights_trigger_api_insights_trigger_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["TriggerRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TriggerResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    insights_weekly_api_insights_weekly_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WeeklySummaryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_proposals_api_v2_agents_proposals_get: {
        parameters: {
            query?: {
                /** @description When true, only return proposals without a matching action_decisions row. The dashboard's review queue uses this; full audit views set false. */
                undecided_only?: boolean;
                limit?: number;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProposalsListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    decide_proposal_api_v2_agents_proposals__proposal_id__decide_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                proposal_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DecideRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DecideResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    v2_apple_batch_api_v2_apple_batch_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    changes_api_v2_changes_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_device_identity_link_api_v2_device_identity_links_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DeviceIdentityLinkCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeviceIdentityLinkResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reconcile_device_identity_link_sessions_api_v2_device_identity_links_session_reconciliations_post: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionFusionReconciliationResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_devices_api_v2_devices_get: {
        parameters: {
            query?: {
                limit?: number | null;
                offset?: number;
                /** @description Owner whose data to read. Admin keys may name any owner (default: the default owner); a participant read key may only name its own. */
                owner?: string | null;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DevicesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_experiments_api_v2_experiments_get: {
        parameters: {
            query?: {
                status?: string | null;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExperimentListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_experiment_api_v2_experiments_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateExperimentRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExperimentView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_candidates_api_v2_experiments_candidates_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_experiment_api_v2_experiments__experiment_id__get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                experiment_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExperimentView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    abandon_experiment_api_v2_experiments__experiment_id__abandon_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                experiment_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExperimentView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    analyze_experiment_api_v2_experiments__experiment_id__analyze_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                experiment_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExperimentView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_data_api_v2_export_get: {
        parameters: {
            query: {
                metric: string;
                format?: string;
                from?: string | null;
                to?: string | null;
                days?: number | null;
                limit?: number | null;
                /** @description Owner whose data to read. Admin keys may name any owner (default: the default owner); a participant read key may only name its own. */
                owner?: string | null;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_export_metrics_api_v2_export_metrics_get: {
        parameters: {
            query?: {
                /** @description Owner whose data to read. Admin keys may name any owner (default: the default owner); a participant read key may only name its own. */
                owner?: string | null;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>[];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_correlations_api_v2_insights_correlations_get: {
        parameters: {
            query?: {
                /** @description Optional day window such as 30d or 90d */
                period?: string | null;
                limit?: number;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_findings_api_v2_insights_findings_get: {
        parameters: {
            query?: {
                /** @description Optional finding kind (anomaly / trend / correlation / summary). */
                type?: string | null;
                limit?: number;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    latest_narratives_api_v2_insights_latest_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_narratives_api_v2_insights_narratives_get: {
        parameters: {
            query?: {
                /** @description daily_briefing or weekly_summary */
                type?: string | null;
                limit?: number;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    trigger_api_v2_insights_trigger_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["TriggerBody"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_intelligence_api_v2_intelligence_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_intelligence_api_v2_intelligence_put: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApplyIntelligenceRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    post_consent_api_v2_intelligence_consent_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConsentRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    detect_local_api_v2_intelligence_detect_local_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    test_connection_api_v2_intelligence_test_connection_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TestConnectionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    index_api_v2_lab_imports_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabImportIndex"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_api_v2_lab_imports_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabImportDraft"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    catalog_api_v2_lab_imports_catalog_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabImportCatalog"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    draft_api_v2_lab_imports__document_id__get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                document_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabImportDraft"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_document_api_v2_lab_imports__document_id__delete: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                document_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LabImportDeletion"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabImportDeletionReceipt"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    commit_api_v2_lab_imports__document_id__commit_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                document_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LabImportReview"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabImportReceipt"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    deletion_preview_api_v2_lab_imports__document_id__deletion_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                document_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabImportDeletionPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    original_api_v2_lab_imports__document_id__original_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                document_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    report_api_v2_lab_imports__document_id__report_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                document_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabImportReport"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_labs_api_v2_labs_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabsOverview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_lab_marker_api_v2_labs__loinc__get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                loinc: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabMarkerDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    v2_meta_api_v2_meta_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
        };
    };
    list_metrics_api_v2_metrics_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>[];
                };
            };
        };
    };
    metric_series_api_v2_metrics__metric_id__series_get: {
        parameters: {
            query?: {
                range?: string;
                stream_id?: string | null;
                /** @description Owner whose data to read. Admin keys may name any owner (default: the default owner); a participant read key may only name its own. */
                owner?: string | null;
            };
            header?: {
                "x-api-key"?: string;
            };
            path: {
                metric_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_moments_api_v2_moments_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MomentListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_moment_api_v2_moments_post: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateMomentRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MomentView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_moment_api_v2_moments__moment_id__put: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                moment_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateMomentRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MomentView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_moment_api_v2_moments__moment_id__delete: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                moment_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    owners_api_v2_owners_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OwnersResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    privacy_api_v2_privacy_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    readiness_api_v2_readiness_get: {
        parameters: {
            query?: {
                /** @description Owner whose data to read. Admin keys may name any owner (default: the default owner); a participant read key may only name its own. */
                owner?: string | null;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_receipts_api_v2_receipts_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    metric_series_batch_api_v2_series_get: {
        parameters: {
            query: {
                ids: string;
                range?: string;
                stream_id?: string | null;
                /** @description Owner whose data to read. Admin keys may name any owner (default: the default owner); a participant read key may only name its own. */
                owner?: string | null;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_analytical_time_api_v2_settings_analytical_time_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnalyticalTimeView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_analytical_time_api_v2_settings_analytical_time_put: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateAnalyticalTimeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnalyticalTimeView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    setup_diagnostics_api_v2_setup_diagnostics_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
        };
    };
    list_sources_api_v2_sources_get: {
        parameters: {
            query?: {
                limit?: number | null;
                offset?: number;
                /** @description Owner whose data to read. Admin keys may name any owner (default: the default owner); a participant read key may only name its own. */
                owner?: string | null;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourcesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    whoop_webhook_api_v2_sources_whoop_webhook_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
        };
    };
    list_streams_api_v2_streams_get: {
        parameters: {
            query?: {
                limit?: number | null;
                offset?: number;
                /** @description Owner whose data to read. Admin keys may name any owner (default: the default owner); a participant read key may only name its own. */
                owner?: string | null;
            };
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StreamsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_stream_api_v2_streams__stream_id__get: {
        parameters: {
            query?: {
                /** @description Owner whose data to read. Admin keys may name any owner (default: the default owner); a participant read key may only name its own. */
                owner?: string | null;
            };
            header?: {
                "x-api-key"?: string;
            };
            path: {
                stream_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StreamView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    sync_anomalies_api_v2_sync_anomalies_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    sync_coverage_api_v2_sync_coverage_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    latest_sync_run_api_v2_sync_runs_latest_get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    sync_run_api_v2_sync_runs__sync_run_id__get: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                sync_run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_sync_run_summary_api_v2_sync_runs__sync_run_id__summary_put: {
        parameters: {
            query?: never;
            header?: {
                "x-api-key"?: string;
            };
            path: {
                sync_run_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SyncRunSummaryPayload"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, never>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    year_in_health_api_v2_year__year__get: {
        parameters: {
            query?: {
                /** @description Owner whose data to read. Admin keys may name any owner (default: the default owner); a participant read key may only name its own. */
                owner?: string | null;
            };
            header?: {
                "x-api-key"?: string;
            };
            path: {
                /** @description Calendar year, like 2026 */
                year: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["YearInHealth"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_check_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    prometheus_metrics_metrics_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    readiness_check_ready_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
}
