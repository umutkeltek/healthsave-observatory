// Experiments page section - candidates + lifecycle stream behind one boundary
// (they render as a single card and share no reads with the shell).

import { ExperimentsCard } from "../ExperimentsCard";
import type { ExperimentPrefill } from "../../lib/experimentPrefill";
import { safeCandidates, safeExperiments } from "../../lib/load";

export async function ExperimentsListSection({
  prefill = null,
}: {
  prefill?: ExperimentPrefill | null;
}) {
  const [experiments, candidates] = await Promise.all([safeExperiments(), safeCandidates()]);
  return (
    <section className="lead">
      <ExperimentsCard experiments={experiments} candidates={candidates} prefill={prefill} />
    </section>
  );
}
