// Privacy page section - one card, one boundary.

import { PrivacyCard } from "../PrivacyCard";
import { safePrivacy } from "../../lib/load";

export async function PrivacySection() {
  const privacy = await safePrivacy();
  return <PrivacyCard privacy={privacy} />;
}
