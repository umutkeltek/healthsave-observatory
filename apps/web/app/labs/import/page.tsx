import type { Metadata } from "next";
import { LabImport } from "../../components/LabImport";
import { participantView } from "../../lib/api";
export const metadata: Metadata = { title: "Import blood tests · HealthSave Observatory" };
export default async function Page() {
  if ((await participantView()).person.kind !== "primary") return <p className="card">Switch to the primary person to view lab documents.</p>;
  return <LabImport />;
}
