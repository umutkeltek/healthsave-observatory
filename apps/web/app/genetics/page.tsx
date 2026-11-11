import type { Metadata } from "next";
import { GeneticHome } from "../components/Genetics";
import { participantView } from "../lib/api";

export const metadata: Metadata = { title: "Genetic evidence · HealthSave Observatory" };
export default async function Page() {
  if ((await participantView()).person.kind !== "primary") return <p className="card">Switch to the primary person to view genetic records.</p>;
  return <GeneticHome />;
}
