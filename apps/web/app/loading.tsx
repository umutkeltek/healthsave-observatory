import { HeroSkeleton, RowSkeleton } from "./components/Skeletons";

// Shown in the content area during route navigation (the shell persists).
// Mirrors the today-page layout so the skeleton → content swap has no shift.
export default function Loading() {
  return (
    <div className="today-page">
      <HeroSkeleton />
      <RowSkeleton />
    </div>
  );
}
