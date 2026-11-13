import { useEffect, useState } from "react";
import { ApiError, getDeclinePath, money, searchSimilarWork } from "../api";
import type { DeclinePath, ProjectDetail, SimilarWork } from "../types";

type Props = { project: ProjectDetail };

export function GraphQueriesPanel({ project }: Props) {
  const openInvoices = project.invoices.filter((invoice) => invoice.status === "SENT");
  const skills = project.project.skills;
  const [invoice, setInvoice] = useState(openInvoices[0]?.number ?? project.invoices[0]?.number ?? "");
  const [skill, setSkill] = useState(skills[0] ?? "Design systems");
  const [decline, setDecline] = useState<DeclinePath | null>(null);
  const [similar, setSimilar] = useState<SimilarWork | null>(null);
  const [declineError, setDeclineError] = useState<string | null>(null);
  const [similarError, setSimilarError] = useState<string | null>(null);
  const [declineBusy, setDeclineBusy] = useState(false);
  const [similarBusy, setSimilarBusy] = useState(false);

  async function loadDecline(number = invoice) {
    if (!number) return;
    setDeclineBusy(true);
    setDeclineError(null);
    try {
      setDecline(await getDeclinePath(number));
    } catch (reason) {
      setDeclineError(
        reason instanceof ApiError ? reason.message : "The decline path could not be loaded.",
      );
    } finally {
      setDeclineBusy(false);
    }
  }

  async function loadSimilar(name = skill) {
    if (!name) return;
    setSimilarBusy(true);
    setSimilarError(null);
    try {
      setSimilar(await searchSimilarWork(name));
    } catch (reason) {
      setSimilarError(
        reason instanceof ApiError ? reason.message : "The paid work could not be loaded.",
      );
    } finally {
      setSimilarBusy(false);
    }
  }

  useEffect(() => {
    void loadDecline(openInvoices[0]?.number ?? project.invoices[0]?.number ?? "");
    void loadSimilar(skills[0] ?? "Design systems");
    // The panel reloads when the project changes, not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.project.id]);

  return (
    <section className="panel graph-queries" aria-labelledby="queries-title">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Graph traversals</p>
          <h2 id="queries-title">Decline paths and paid history</h2>
        </div>
        <p className="panel-count">Same queries the assistant uses</p>
      </div>

      <div className="query-grid">
        <div className="query-card">
          <h3>Blocked until this invoice is paid</h3>
          <p className="query-copy">
            Walks <code>DEPENDS_ON</code> from the invoice's milestone and lists every downstream
            milestone that stays blocked.
          </p>
          <div className="query-controls">
            <label htmlFor="decline-invoice">Invoice</label>
            <select
              id="decline-invoice"
              value={invoice}
              onChange={(event) => setInvoice(event.target.value)}
            >
              {project.invoices.map((item) => (
                <option key={item.id} value={item.number}>
                  {item.number} · {item.status}
                </option>
              ))}
            </select>
            <button
              className="btn btn-secondary btn-small"
              type="button"
              onClick={() => void loadDecline()}
              disabled={declineBusy}
            >
              {declineBusy ? "Tracing…" : "Show decline path"}
            </button>
          </div>
          {declineError && (
            <p className="alert alert-error" role="alert">
              {declineError}
            </p>
          )}
          {decline && (
            <div className="query-result" aria-live="polite">
              <p>
                Invoice <code>{decline.invoice.number}</code> ·{" "}
                {money(decline.invoice.amount_cents)} · {decline.blocked_count} blocked
              </p>
              {decline.blocked.length === 0 ? (
                <p className="query-empty">No downstream milestone waits on this invoice.</p>
              ) : (
                <ul>
                  {decline.blocked.map((row) => (
                    <li key={row.blocked_id}>
                      <strong>{row.blocked}</strong> <code>{row.blocked_id}</code>{" "}
                      <span className="query-status">{row.status}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <div className="query-card">
          <h3>Who has been paid for this skill?</h3>
          <p className="query-copy">
            Joins <code>NEEDS_SKILL</code>, <code>WORKED_ON</code>, <code>HAS_SKILL</code> and the
            paid invoice path, so only paid milestones count.
          </p>
          <div className="query-controls">
            <label htmlFor="similar-skill">Skill</label>
            <select
              id="similar-skill"
              value={skill}
              onChange={(event) => setSkill(event.target.value)}
            >
              {skills.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <button
              className="btn btn-secondary btn-small"
              type="button"
              onClick={() => void loadSimilar()}
              disabled={similarBusy}
            >
              {similarBusy ? "Searching…" : "Show paid work"}
            </button>
          </div>
          {similarError && (
            <p className="alert alert-error" role="alert">
              {similarError}
            </p>
          )}
          {similar && (
            <div className="query-result" aria-live="polite">
              {similar.work.length === 0 ? (
                <p className="query-empty">No paid milestone uses {similar.skill}.</p>
              ) : (
                <ul>
                  {similar.work.map((row) => (
                    <li key={`${row.party}-${row.invoice}-${row.milestone}`}>
                      <strong>{row.party}</strong> on {row.project}, {row.milestone} ·{" "}
                      <code>{row.invoice}</code> · {money(row.amount_cents)}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
