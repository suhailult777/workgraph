import { money } from "../api";
import type { Blocker, Milestone, ProjectDetail } from "../types";
import { GraphQueriesPanel } from "./GraphQueriesPanel";
import { GraphView } from "./GraphView";
import { StatusChip } from "./StatusChip";

type Props = {
  project: ProjectDetail | null;
  loading: boolean;
  error: string | null;
  actionError: string | null;
  completingId: string | null;
  storeLabel: string;
  onBack: () => void;
  onRetry: () => void;
  onRecordPayment: (invoiceId: string) => void;
  onComplete: (milestone: Milestone) => void;
  onDismissActionError: () => void;
};

function blockerReason(blocker: Blocker): string {
  if (blocker.reason === "unpaid_invoice") {
    return `Unpaid invoice ${blocker.invoice ?? ""} · ${money(blocker.amount_cents ?? 0)}`;
  }
  return `${blocker.path[blocker.path.length - 1]} is not marked done`;
}

function MilestoneActions({
  milestone,
  completingId,
  onRecordPayment,
  onComplete,
}: {
  milestone: Milestone;
  completingId: string | null;
  onRecordPayment: (invoiceId: string) => void;
  onComplete: (milestone: Milestone) => void;
}) {
  if (milestone.status === "DONE") {
    return <span className="action-note action-done">Accepted ✓</span>;
  }
  if (milestone.invoice?.status === "SENT") {
    if (!milestone.can_pay) {
      return (
        <span className="action-note" title={milestone.pay_block_reason ?? undefined}>
          Payment unavailable
        </span>
      );
    }
    return (
      <button
        className="btn btn-primary btn-small"
        type="button"
        onClick={() => onRecordPayment(milestone.invoice!.id)}
      >
        Record sample payment
      </button>
    );
  }
  if (milestone.can_complete) {
    return (
      <button
        className="btn btn-secondary btn-small"
        type="button"
        disabled={completingId === milestone.id}
        onClick={() => onComplete(milestone)}
      >
        {completingId === milestone.id ? "Marking done…" : "Mark milestone done"}
      </button>
    );
  }
  if (milestone.invoice?.status === "PAID") {
    return <span className="action-note">Waiting on prerequisites</span>;
  }
  return <span className="action-note">Blocked by the plan</span>;
}

export function ProjectView({
  project,
  loading,
  error,
  actionError,
  completingId,
  storeLabel,
  onBack,
  onRetry,
  onRecordPayment,
  onComplete,
  onDismissActionError,
}: Props) {
  if (loading && !project) {
    return (
      <div className="project-loading" aria-busy="true" aria-live="polite">
        <span className="skeleton skeleton-line short" />
        <span className="skeleton skeleton-line title" />
        <span className="skeleton skeleton-block tall" />
        <p>Reading the project graph…</p>
      </div>
    );
  }

  if (error && !project) {
    return (
      <div className="empty-state" role="alert">
        <p className="empty-kicker">Project unavailable</p>
        <h1>The project could not be loaded.</h1>
        <p>{error}</p>
        <div className="empty-actions">
          <button className="btn btn-secondary" type="button" onClick={onBack}>
            Back to projects
          </button>
          <button className="btn btn-primary" type="button" onClick={onRetry}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  if (!project) return null;

  const { project: info, stats, milestones, invoices, payments } = project;
  const blockedMilestones = milestones.filter((milestone) => milestone.blocked_by.length > 0);
  const paymentTotal = payments.reduce((sum, payment) => sum + payment.amount_cents, 0);

  return (
    <>
      <button className="back-link" type="button" onClick={onBack}>
        <span aria-hidden="true">←</span> All projects
      </button>

      <header className="project-head">
        <div>
          <p className="eyebrow">Project · {info.status}</p>
          <h1>{info.name}</h1>
          <p className="lede project-lede">
            {info.client ? `${info.client} commissioned the work.` : "Independent sample project."}{" "}
            {info.owner ? `${info.owner} owns the delivery.` : ""}
          </p>
        </div>
        <div className="project-head-side">
          <StatusChip status={info.status} />
          <p className="store-note">
            Graph file <code>{storeLabel}</code>
          </p>
          <p className="store-note muted-small">Same graph the agent reads</p>
        </div>
      </header>

      {actionError && (
        <div className="alert alert-error action-alert" role="alert">
          <span>{actionError}</span>
          <button className="alert-dismiss" type="button" onClick={onDismissActionError} aria-label="Dismiss error">
            ×
          </button>
        </div>
      )}

      <section className="stat-strip" aria-label="Project summary">
        <div className="stat">
          <span className="stat-value">
            {money(stats.paid_cents)} <span className="stat-fraction">/ {money(stats.total_cents)}</span>
          </span>
          <span className="stat-label">paid · total</span>
        </div>
        <div className="stat">
          <span className="stat-value">
            {stats.done} <span className="stat-fraction">/ {stats.milestones}</span>
          </span>
          <span className="stat-label">milestones done</span>
        </div>
        <div className="stat">
          <span className="stat-value">{stats.blocked}</span>
          <span className="stat-label">blocked by a path</span>
        </div>
        <div className="stat">
          <span className="stat-value">{stats.unlocked_deliverables}</span>
          <span className="stat-label">deliverables unlocked</span>
        </div>
      </section>

      <section className="panel graph-panel" aria-labelledby="graph-title">
        <div className="panel-head">
          <div>
            <p className="eyebrow">Relationships</p>
            <h2 id="graph-title">Project graph</h2>
          </div>
          <ul className="graph-legend" aria-label="Edge legend">
            <li>
              <span className="legend-swatch legend-depends" aria-hidden="true" /> depends on
            </li>
            <li>
              <span className="legend-swatch legend-money" aria-hidden="true" /> money moves
            </li>
            <li>
              <span className="legend-swatch legend-invoice" aria-hidden="true" /> invoice
            </li>
            <li>
              <span className="legend-swatch legend-produces" aria-hidden="true" /> produces
            </li>
          </ul>
        </div>
        <GraphView nodes={project.graph.nodes} edges={project.graph.edges} />
        <p className="graph-note">
          Dependency arrows point to the prerequisite. Payment arrows point from the sample payment
          to the deliverable it unlocks.
        </p>
      </section>

      <GraphQueriesPanel project={project} />

      <div className="detail-grid">
        <section className="panel plan-panel" aria-labelledby="plan-title">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Plan</p>
              <h2 id="plan-title">Milestone trail</h2>
            </div>
            <p className="panel-count">{milestones.length} milestones</p>
          </div>
          {milestones.length === 0 ? (
            <div className="empty-inline">
              <h3>This project has no milestones yet.</h3>
              <p>Create a sample project to get a full dependency chain.</p>
            </div>
          ) : (
            <ol className="milestone-list">
              {milestones.map((milestone, index) => (
                <li
                  key={milestone.id}
                  className={`milestone${milestone.blocked ? " is-blocked" : ""}`}
                >
                  <span className="milestone-index" aria-hidden="true">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div className="milestone-body">
                    <div className="milestone-head">
                      <h3>{milestone.name}</h3>
                      <StatusChip status={milestone.status} />
                    </div>
                    <p className="milestone-meta">
                      {money(milestone.amount_cents)}
                      {milestone.invoice ? (
                        <>
                          {" "}
                          · invoice <code>{milestone.invoice.number}</code>
                        </>
                      ) : (
                        " · no invoice"
                      )}
                    </p>
                    <p className="milestone-depends">
                      {milestone.parents.length === 0
                        ? "No prerequisites."
                        : `After ${milestone.parents.map((parent) => parent.name).join(", ")}.`}
                    </p>
                    {milestone.deliverables.length > 0 && (
                      <ul className="deliverable-list">
                        {milestone.deliverables.map((deliverable) => (
                          <li key={deliverable.id} className={deliverable.unlocked ? "is-unlocked" : ""}>
                            <span className="deliverable-mark" aria-hidden="true">
                              {deliverable.unlocked ? "◆" : "◇"}
                            </span>
                            {deliverable.name}
                            <span className="deliverable-state">
                              {deliverable.unlocked ? "unlocked" : "locked"}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                    {milestone.blocked_by.length > 0 && (
                      <div className="milestone-blocked">
                        <span className="blocked-label">Blocked</span>
                        {milestone.blocked_by.map((blocker) => (
                          <span key={`${blocker.path.join("-")}-${blocker.reason}`} className="blocked-path">
                            {blocker.path.join(" → ")}
                            <em>{blockerReason(blocker)}</em>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="milestone-actions">
                    <MilestoneActions
                      milestone={milestone}
                      completingId={completingId}
                      onRecordPayment={onRecordPayment}
                      onComplete={onComplete}
                    />
                  </div>
                </li>
              ))}
            </ol>
          )}
        </section>

        <aside className="detail-aside">
          <section className="panel blocked-panel" aria-labelledby="blocked-title">
            <div className="panel-head">
              <div>
                <p className="eyebrow">Dependency paths</p>
                <h2 id="blocked-title">Blocked now</h2>
              </div>
              <span className="panel-count">{blockedMilestones.length}</span>
            </div>
            {blockedMilestones.length === 0 ? (
              <p className="aside-empty">
                Nothing is blocked. Every prerequisite in this project is done.
              </p>
            ) : (
              <div className="blocked-list">
                {blockedMilestones.map((milestone) => (
                  <article key={milestone.id} className="blocked-entry">
                    <h3>{milestone.name}</h3>
                    {milestone.blocked_by.map((blocker) => (
                      <div key={`${blocker.path.join("-")}-${blocker.reason}`} className="blocker">
                        <p className="blocker-path">
                          {blocker.path.map((step, index) => (
                            <span key={`${step}-${index}`}>
                              {index > 0 && <span className="path-arrow"> → </span>}
                              {step}
                            </span>
                          ))}
                        </p>
                        <p className="blocker-reason">{blockerReason(blocker)}</p>
                      </div>
                    ))}
                  </article>
                ))}
              </div>
            )}
            <p className="aside-note">
              A milestone can be done only after its prerequisites are done and its own invoice is
              paid.
            </p>
          </section>

          <section className="panel ledger-panel" aria-labelledby="ledger-title">
            <div className="panel-head">
              <div>
                <p className="eyebrow">Ledger</p>
                <h2 id="ledger-title">Invoices</h2>
              </div>
              <span className="panel-count">{invoices.length}</span>
            </div>
            {invoices.length === 0 ? (
              <p className="aside-empty">No invoices in this project yet.</p>
            ) : (
              <ul className="ledger-list">
                {invoices.map((invoice) => (
                  <li key={invoice.id}>
                    <div>
                      <code>{invoice.number}</code>
                      <span className="ledger-milestone">
                        {milestones.find((milestone) => milestone.invoice?.id === invoice.id)?.name}
                      </span>
                    </div>
                    <div className="ledger-right">
                      <span className="ledger-amount">{money(invoice.amount_cents)}</span>
                      <StatusChip status={invoice.status} quiet />
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <div className="ledger-total">
              <span>Sample payments recorded</span>
              <strong>{money(paymentTotal)}</strong>
            </div>
            <p className="aside-note">Method is always <code>sample</code>. No card or live PayPal call.</p>
          </section>
        </aside>
      </div>
    </>
  );
}
