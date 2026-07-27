"use server";

// Server actions for the experiment write surface. These run on the Next server
// (never the browser), so the X-API-Key injected by lib/api.ts stays private.
// Each revalidates "/" so the dashboard re-renders with the new state.

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";

import {
  abandonExperiment,
  analyzeExperiment,
  applyIntelligence,
  type ApplyIntelligencePayload,
  type ConsentPayload,
  createExperiment,
  type CreateMomentPayload,
  createMoment,
  type DetectCandidate,
  fetchDetectLocal,
  postConsent,
  postInsightsTrigger,
  postTestConnection,
  type TestConnectionPayload,
  type TestConnectionResult,
  type UpdateAnalyticalTimePayload,
  updateAnalyticalTime,
} from "./api";
import {
  type Density,
  DENSITY_COOKIE,
  type FocusGoal,
  FOCUS_GOAL_COOKIE,
  MAX_PINS,
  parseFocusGoal,
  parsePinned,
  PINNED_COOKIE,
} from "./prefs";

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

// Intelligence (LLM narrator) settings. Apply + consent revalidate both the
// settings page and the shell (the egress chip reads the same posture);
// test-connection performs no write, so it only returns the probe result.

export async function applyIntelligenceAction(
  payload: ApplyIntelligencePayload,
): Promise<ActionResult> {
  try {
    await applyIntelligence(payload);
    revalidatePath("/intelligence");
    revalidatePath("/");
    return { ok: true };
  } catch (error) {
    return failure(error, "Could not save Intelligence settings.");
  }
}

export async function consentAction(payload: ConsentPayload): Promise<ActionResult> {
  try {
    await postConsent(payload);
    revalidatePath("/intelligence");
    revalidatePath("/");
    return { ok: true };
  } catch (error) {
    return failure(error, "Could not update consent.");
  }
}

export type TestActionResult = ActionResult & { result?: TestConnectionResult };

export async function testConnectionAction(
  payload: TestConnectionPayload,
): Promise<TestActionResult> {
  try {
    const result = await postTestConnection(payload);
    return { ok: true, result };
  } catch (error) {
    return failure(error, "Could not reach the provider.");
  }
}

export type DetectActionResult = ActionResult & { candidates?: DetectCandidate[] };

export async function detectLocalAction(): Promise<DetectActionResult> {
  try {
    const { candidates } = await fetchDetectLocal();
    return { ok: true, candidates };
  } catch (error) {
    return failure(error, "Could not probe for a local model.");
  }
}

export async function updateAnalyticalTimeAction(
  payload: UpdateAnalyticalTimePayload,
): Promise<ActionResult> {
  try {
    await updateAnalyticalTime(payload);
    revalidatePath("/settings");
    revalidatePath("/data");
    revalidatePath("/explore");
    revalidatePath("/relationships");
    return { ok: true };
  } catch (error) {
    return failure(error, "Could not save analytical time settings.");
  }
}

// ── Moment actions ──────────────────────────────────────────────────

export async function createMomentAction(
  payload: CreateMomentPayload,
): Promise<ActionResult> {
  try {
    await createMoment(payload);
    revalidatePath("/timeline");
    revalidatePath("/");
    return { ok: true };
  } catch (error) {
    return failure(error, "Could not add this moment.");
  }
}

// ── Preference actions (cookie-backed; see lib/prefs.ts) ──────────────

export async function togglePinAction(metricId: string): Promise<ActionResult> {
  try {
    const jar = await cookies();
    const pinned = parsePinned(jar.get(PINNED_COOKIE)?.value);
    const next = pinned.includes(metricId)
      ? pinned.filter((id) => id !== metricId)
      : [...pinned, metricId].slice(0, MAX_PINS);
    jar.set(PINNED_COOKIE, JSON.stringify(next), {
      path: "/",
      maxAge: 60 * 60 * 24 * 365,
      sameSite: "lax",
      httpOnly: true,
    });
    revalidatePath("/");
    revalidatePath("/library");
    return { ok: true };
  } catch (error) {
    return failure(error, "Could not update pinned signals.");
  }
}

export async function setDensityAction(mode: Density): Promise<ActionResult> {
  try {
    const jar = await cookies();
    jar.set(DENSITY_COOKIE, mode === "observatory" ? "observatory" : "essentials", {
      path: "/",
      maxAge: 60 * 60 * 24 * 365,
      sameSite: "lax",
      httpOnly: true,
    });
    // No explicit revalidate: cookie writes in a server action already
    // invalidate the router cache, and every page is dynamic - the old
    // revalidatePath("/", "layout") forced a full re-render storm that made
    // the toggle feel sluggish. The nav itself is optimistic client state.
    return { ok: true };
  } catch (error) {
    return failure(error, "Could not switch the view mode.");
  }
}

export async function setFocusGoalAction(goal: FocusGoal): Promise<ActionResult> {
  try {
    // Round-trip through the parser so only a well-formed goal is ever stored.
    const clean = parseFocusGoal(JSON.stringify(goal));
    if (!clean) return { ok: false, error: "That goal is missing a title or metrics." };
    const jar = await cookies();
    jar.set(FOCUS_GOAL_COOKIE, JSON.stringify(clean), {
      path: "/",
      maxAge: 60 * 60 * 24 * 365,
      sameSite: "lax",
      httpOnly: true,
    });
    revalidatePath("/");
    return { ok: true };
  } catch (error) {
    return failure(error, "Could not set the focus goal.");
  }
}

export async function clearFocusGoalAction(): Promise<ActionResult> {
  try {
    const jar = await cookies();
    jar.delete(FOCUS_GOAL_COOKIE);
    revalidatePath("/");
    return { ok: true };
  } catch (error) {
    return failure(error, "Could not clear the focus goal.");
  }
}

export type TriggerAnalysisResult = ActionResult & { status?: string };

// On-demand narration/analysis refresh (the Weekly Brief card's button). A
// 409 means the analysis block is disabled - the card surfaces that calmly
// with a link to /intelligence instead of an error tone.
export async function triggerAnalysisAction(
  type: "correlation_analysis" | "recovery_check" | "daily_briefing" | "weekly_summary",
): Promise<TriggerAnalysisResult> {
  try {
    const result = await postInsightsTrigger(type);
    revalidatePath("/");
    revalidatePath("/findings");
    revalidatePath("/relationships");
    return { ok: true, status: result.status };
  } catch (error) {
    return failure(error, "Could not run the analysis.");
  }
}
