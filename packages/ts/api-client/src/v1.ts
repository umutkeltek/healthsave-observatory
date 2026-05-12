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
         *     Reads through :func:`storage.timescale.agents.fetch_recent_proposals`
         *     — the Phase 7-B repository owns the SQL (default newest-first via
         *     the supplied ORDER BY). Per the Phase 5 storage-zone rule, the
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
         *     :func:`storage.timescale.agents.decide_action`. The decision is
         *     append-only — re-deciding (e.g. flipping a rejection to an
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
