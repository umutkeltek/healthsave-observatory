import { ActivityPageSkeleton } from "../components/Skeletons";

// Shown while the activity data streams in. Mirrors the activity page layout
// so the skeleton → content swap has no layout shift.
export default function ActivityLoading() {
  return <ActivityPageSkeleton />;
}
