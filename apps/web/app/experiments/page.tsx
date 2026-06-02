import { ExperimentsCard } from "../components/ExperimentsCard";
import { safeCandidates, safeExperiments } from "../lib/load";

export const dynamic = "force-dynamic";

export default async function ExperimentsPage() {
  const [experiments, candidates] = await Promise.all([safeExperiments(), safeCandidates()]);
  return (
    <section className="lead">
      <ExperimentsCard experiments={experiments} candidates={candidates} />
    </section>
  );
}
