import { LabReport } from "../../../../components/LabReport";
import { participantView } from "../../../../lib/api";
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  if ((await participantView()).person.kind !== "primary") return <p className="card">Switch to the primary person to view lab documents.</p>;
  return <LabReport documentId={(await params).id} />;
}
