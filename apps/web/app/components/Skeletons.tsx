// Dimension-matched placeholders for Suspense-streamed sections. Sizes mirror
// the settled components (hero ~220px, cards ~180px) so streaming causes no
// layout shift; the shimmer rides the existing .sk styles.
// Each skeleton mimics the layout grid of the component it replaces — a wrong
// shape causes a visible jump when React swaps the skeleton for real content.

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
    <section className="hero today-hero skeleton-card" aria-hidden>
      <div className="today-hero-main">
        <div className="hero-lede">
          <div className="sk sk-eyebrow" />
          <div className="sk sk-line lg" style={{ height: 36, maxWidth: 420 }} />
          <div className="sk sk-line" style={{ height: 56, maxWidth: 340 }} />
        </div>
        <div style={{ width: 220, height: 220 }} aria-hidden />
      </div>
    </section>
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
    <section className="grid today-signals-grid" aria-hidden>
      {Array.from({ length: count }, (_, i) => (
        <article key={i} className="card metric-card skeleton-card" aria-hidden>
          <div className="metric-card-head">
            <div className="sk sk-eyebrow" style={{ width: "40%" }} />
          </div>
          <div className="sk sk-line lg" style={{ height: 32, maxWidth: 100 }} />
          <div style={{ height: 54 }} aria-hidden />
          <div className="sk sk-line sm" style={{ maxWidth: "60%" }} />
        </article>
      ))}
    </section>
  );
}

export function LeadSkeleton() {
  return <CardSkeleton />;
}
