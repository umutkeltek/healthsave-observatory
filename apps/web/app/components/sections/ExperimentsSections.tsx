// Experiments page section — candidates + lifecycle stream behind one boundary
// (they render as a single card and share no reads with the shell).

import { ExperimentsCard } from "../ExperimentsCard";
import { safeCandidates, safeExperiments } from "../../lib/load";

export async function ExperimentsListSection() {
  const [experiments, candidates] = await Promise.all([safeExperiments(), safeCandidates()]);
  return (
    <section className="lead">
      <ExperimentsCard experiments={experiments} candidates={candidates} />
    </section>
  );
}
