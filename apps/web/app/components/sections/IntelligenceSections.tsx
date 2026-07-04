// Intelligence page section - the settings form and privacy card share one
// boundary (the form needs both reads before it can render its initial state).

import { IntelligenceSettings } from "../IntelligenceSettings";
import { safeIntelligence, safePrivacy } from "../../lib/load";

export async function IntelligenceSection() {
  const [intelligence, privacy] = await Promise.all([safeIntelligence(), safePrivacy()]);
  return <IntelligenceSettings initial={intelligence} privacy={privacy} />;
}
