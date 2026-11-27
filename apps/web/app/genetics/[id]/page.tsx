import { GeneticDocumentView } from "../../components/Genetics";
import { participantView } from "../../lib/api";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  if ((await participantView()).person.kind !== "primary") return <p className="card">Switch to the primary person to view genetic records.</p>;
  const { id } = await params;
  return <GeneticDocumentView key={id} documentId={id} />;
}
