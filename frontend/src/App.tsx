import { useEffect, useState } from "react";

type Summary = {
  labels: { label: string; count: number }[];
  projects: { id: string; name: string; status: string }[];
  milestones: { project: string; milestone: string; status: string }[];
};

type Blocked = {
  blocked: string;
  waiting_on: string;
  invoice: string;
  amount_cents: number;
};

type Health = { status: string; store: string; graph_ready: boolean };

const money = (cents: number) =>
  new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(
    cents / 100,
  );

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [blocked, setBlocked] = useState<Blocked[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([
      fetch("/api/health").then((r) => r.json()),
      fetch("/api/graph/summary").then((r) => r.json()),
      fetch("/api/graph/blocked").then((r) => r.json()),
    ])
      .then(([h, s, b]) => {
        if (!live) return;
        setHealth(h);
        setSummary(s);
        setBlocked(b.blocked);
      })
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, []);

  return (
    <main>
      <header className="masthead">
        <p className="eyebrow">Phase 0 spike</p>
        <h1>WorkGraph</h1>
        <p className="lede">
          Freelance projects, milestone dependencies and sample payments in one persistent graph.
          Agents and people read the same nodes.
        </p>
      </header>

      {error && <p className="error">Could not read the graph: {error}</p>}

      <section className="grid">
        <article className="card">
          <h2>Service</h2>
          {health ? (
            <>
              <p className="big">{health.status}</p>
              <p className="muted">Graph ready: {health.graph_ready ? "yes" : "no"}</p>
              <p className="path">{health.store}</p>
            </>
          ) : (
            <p className="muted">Reading…</p>
          )}
        </article>

        <article className="card">
          <h2>Graph shape</h2>
          {summary ? (
            <ul className="chips">
              {summary.labels.map((l) => (
                <li key={l.label}>
                  <strong>{l.count}</strong> {l.label}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Reading…</p>
          )}
        </article>
      </section>

      <section className="panel">
        <h2>Blocked by an unpaid invoice</h2>
        {blocked.length === 0 ? (
          <p className="muted">No blocked milestones in the seed graph.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th scope="col">Milestone</th>
                <th scope="col">Waits on</th>
                <th scope="col">Invoice</th>
                <th scope="col">Amount</th>
              </tr>
            </thead>
            <tbody>
              {blocked.map((b) => (
                <tr key={`${b.blocked}-${b.invoice}`}>
                  <td>{b.blocked}</td>
                  <td>{b.waiting_on}</td>
                  <td><code>{b.invoice}</code></td>
                  <td className="num">{money(b.amount_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted">
          The query walks one to three <code>DEPENDS_ON</code> hops, then follows{" "}
          <code>INVOICED</code> to an invoice with status <code>SENT</code>. Amounts are sample
          units stored as integer cents.
        </p>
      </section>

      <section className="panel">
        <h2>Projects</h2>
        <div className="projects">
          {summary?.projects.map((p) => (
            <article key={p.id}>
              <h3>{p.name}</h3>
              <p className="status">{p.status}</p>
              <ul>
                {summary.milestones
                  .filter((m) => m.project === p.name)
                  .map((m) => (
                    <li key={m.milestone}>
                      <span>{m.milestone}</span>
                      <span className={`dot ${m.status.toLowerCase()}`}>{m.status}</span>
                    </li>
                  ))}
              </ul>
            </article>
          ))}
        </div>
      </section>

      <footer>
        <p>
          Sample data only. Read-only build. The assistant network is published at{" "}
          <a href="/agent-manifest.json">/agent-manifest.json</a>.
        </p>
      </footer>
    </main>
  );
}
