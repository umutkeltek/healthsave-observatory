// Dimension-matched placeholders for Suspense-streamed sections. Sizes mirror
// the settled components (hero ~220px, cards ~180px) so streaming causes no
// layout shift; the shimmer rides the existing .sk styles.

export function CardSkeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`card skeleton-card ${className}`} aria-hidden>
      <div className="sk sk-eyebrow" />
      <div className="sk sk-line lg" />
      <div className="sk sk-line" />
      <div className="sk sk-line sm" />
    </div>
  );
}

export function HeroSkeleton() {
  return (
    <article className="hero skeleton-card" aria-hidden>
      <div className="sk sk-eyebrow" />
      <div className="sk sk-line lg" style={{ height: 44, maxWidth: 280 }} />
      <div className="sk sk-line" />
      <div className="sk sk-line" style={{ height: 56 }} />
    </article>
  );
}

export function RowSkeleton() {
  return (
    <div className="row-2">
      <CardSkeleton />
      <CardSkeleton />
    </div>
  );
}

export function GridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <section className="grid" aria-hidden>
      {Array.from({ length: count }, (_, i) => (
        <CardSkeleton key={i} />
      ))}
    </section>
  );
}

export function LeadSkeleton() {
  return (
    <section className="lead">
      <CardSkeleton />
    </section>
  );
}
