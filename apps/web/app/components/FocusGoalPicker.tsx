"use client";

import { useState, useTransition } from "react";

import { clearFocusGoalAction, setFocusGoalAction } from "../lib/actions";
import type { FocusGoal } from "../lib/prefs";

// Curated focus presets - every metric id is a real ontology id, so the
// ribbon's sparklines and the goal-first Today ordering always resolve.
// Custom/free-text goals arrive with the DB-backed Goals API (migration 021).
export const GOAL_PRESETS: FocusGoal[] = [
  {
    title: "Recover better",
    direction: "increase",
    metricIds: ["vital.hrv_sdnn", "vital.resting_heart_rate", "sleep.duration"],
  },
  {
    title: "Sleep better",
    direction: "increase",
    metricIds: ["sleep.duration", "vital.respiratory_rate", "vital.resting_heart_rate"],
  },
  {
    title: "Get fitter",
    direction: "increase",
    metricIds: ["cardio.vo2_max", "activity.exercise_minutes", "activity.steps"],
  },
  {
    title: "Lower resting heart rate",
    direction: "decrease",
    metricIds: ["vital.resting_heart_rate", "vital.hrv_sdnn", "activity.steps"],
  },
  {
    title: "Manage weight",
    direction: "decrease",
    metricIds: ["body.weight", "activity.active_energy", "activity.steps"],
  },
];

export function FocusGoalPicker({ active }: { active: FocusGoal | null }) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const choose = (goal: FocusGoal) => {
    setError(null);
    startTransition(async () => {
      const result =
        active?.title === goal.title ? await clearFocusGoalAction() : await setFocusGoalAction(goal);
      if (!result.ok) setError(result.error ?? "Could not update the focus goal.");
    });
  };

  return (
    <div className="goal-picker" data-pending={pending || undefined}>
      {GOAL_PRESETS.map((goal) => {
        const isActive = active?.title === goal.title;
        return (
          <button
            key={goal.title}
            type="button"
            className={`goal-chip ${isActive ? "is-active" : ""}`}
            onClick={() => choose(goal)}
            disabled={pending}
            aria-pressed={isActive}
          >
            {goal.title}
          </button>
        );
      })}
      {error && <span className="goal-error">{error}</span>}
    </div>
  );
}
