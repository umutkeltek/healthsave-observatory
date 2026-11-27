// Experiment status as the server defines it (server/api/v2_experiments.py).
// The wire field stays a string; this is the one place that decides what it
// means, so no card compares raw strings on its own.
//   collecting - running: the only state that blocks starting the same pair
//   completed  - finished; the pair can be tested again
//   abandoned  - stopped
//   unknown    - a value this web build does not know; treated as not running
export type ExperimentStatus = "collecting" | "completed" | "abandoned" | "unknown";

export function experimentStatus(raw: string): ExperimentStatus {
  return raw === "collecting" || raw === "completed" || raw === "abandoned" ? raw : "unknown";
}

export function isRunning(raw: string): boolean {
  return experimentStatus(raw) === "collecting";
}

/** A lever/outcome pair, unordered: A→B and B→A are the same pair. */
export function pairKey(lever: string | null, outcome: string | null): string {
  return [lever ?? "", outcome ?? ""].sort().join("~");
}

/** Pairs with an experiment still collecting - the ones not to offer again. */
export function runningPairKeys(
  experiments: readonly { status: string; lever_metric_id: string; outcome_metric_id: string }[],
): Set<string> {
  return new Set(
    experiments.filter((e) => isRunning(e.status)).map((e) => pairKey(e.lever_metric_id, e.outcome_metric_id)),
  );
}
