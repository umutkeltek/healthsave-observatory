import { LabImport } from "../../../components/LabImport";
import { participantView } from "../../../lib/api";
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  if ((await participantView()).person.kind !== "primary") return <p className="card">Switch to the primary person to view lab documents.</p>;
  return <LabImport documentId={(await params).id} />;
}
