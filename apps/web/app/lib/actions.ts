"use server";

// Server actions for the experiment write surface. These run on the Next server
// (never the browser), so the X-API-Key injected by lib/api.ts stays private.
// Each revalidates "/" so the dashboard re-renders with the new state.

import { revalidatePath } from "next/cache";

import { abandonExperiment, analyzeExperiment, createExperiment } from "./api";

export type ActionResult = { ok: boolean; error?: string };

function failure(error: unknown, fallback: string): ActionResult {
  return { ok: false, error: error instanceof Error ? error.message : fallback };
}

export async function startExperimentAction(
  leverMetricId: string,
  outcomeMetricId: string,
): Promise<ActionResult> {
  try {
    await createExperiment({ lever_metric_id: leverMetricId, outcome_metric_id: outcomeMetricId });
    revalidatePath("/");
    return { ok: true };
  } catch (error) {
    return failure(error, "Could not start the experiment.");
  }
}

export async function analyzeExperimentAction(id: string): Promise<ActionResult> {
  try {
    await analyzeExperiment(id);
    revalidatePath("/");
    return { ok: true };
  } catch (error) {
    return failure(error, "Could not analyze the experiment.");
  }
}

export async function abandonExperimentAction(id: string): Promise<ActionResult> {
  try {
    await abandonExperiment(id);
    revalidatePath("/");
    return { ok: true };
  } catch (error) {
    return failure(error, "Could not stop the experiment.");
  }
}
