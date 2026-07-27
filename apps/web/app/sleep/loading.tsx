import { SleepPageSkeleton } from "../components/Skeletons";

// Shown while the sleep data streams in. Mirrors the sleep page layout so
// the skeleton → content swap has no layout shift.
export default function SleepLoading() {
  return <SleepPageSkeleton />;
}
