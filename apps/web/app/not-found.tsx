import Link from "next/link";

export default function NotFound() {
  return (
    <section className="lead">
      <article className="card">
        <h2>Not found</h2>
        <div className="big">404</div>
        <p className="empty">That view doesn&apos;t exist in this console.</p>
        <div className="exp-action">
          <Link className="btn" href="/">
            Back to Overview
          </Link>
        </div>
      </article>
    </section>
  );
}
