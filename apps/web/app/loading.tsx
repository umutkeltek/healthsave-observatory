// Shown in the content area during route navigation (the shell persists).
export default function Loading() {
  return (
    <>
      <section className="lead">
        <div className="card skeleton-card" aria-hidden>
          <div className="sk sk-eyebrow" />
          <div className="sk sk-line lg" />
          <div className="sk sk-line" />
          <div className="sk sk-line sm" />
        </div>
      </section>
      <section className="lead">
        <div className="card skeleton-card" aria-hidden>
          <div className="sk sk-eyebrow" />
          <div className="sk sk-line" />
          <div className="sk sk-line" />
          <div className="sk sk-line sm" />
        </div>
      </section>
    </>
  );
}
