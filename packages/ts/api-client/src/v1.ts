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
         *     finding's severity column.
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
         *     ``app.state.analysis_engine``. Future job types (weekly,
         *     correlation, etc.) should dispatch via ``request.app.state.scheduler``
         *     once their engine methods land.
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
