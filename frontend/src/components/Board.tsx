import { useState } from "react";
import { money } from "../api";
import type { ProjectSummary } from "../types";
import { StatusChip } from "./StatusChip";

type Props = {
  projects: ProjectSummary[] | null;
  loading: boolean;
  error: string | null;
  creating: boolean;
  createError: string | null;
  onCreate: (name: string) => void;
  onRetry: () => void;
};

function Track({ project }: { project: ProjectSummary }) {
  return (
    <div
      className="track"
      role="img"
      aria-label={project.milestone_states
        .map((m) => `${m.name}: ${m.status.toLowerCase()}`)
        .join(", ")}
    >
      {project.milestone_states.map((milestone) => (
        <span
          key={milestone.id}
          className={`track-segment track-${milestone.status.toLowerCase()}`}
          title={`${milestone.name}: ${milestone.status}`}
        />
      ))}
    </div>
  );
}

function ProjectCard({ project }: { project: ProjectSummary }) {
  const progress = project.milestones === 0 ? 0 : Math.round((project.done / project.milestones) * 100);
  return (
    <article className="project-card">
      <div className="project-card-top">
        <span className="project-client">{project.client ?? "Independent project"}</span>
        <span className="project-state">{project.status}</span>
      </div>
      <h3>{project.name}</h3>
      <p className="project-progress">
        <strong>{project.done}</strong> of {project.milestones} milestones done
        <span className="project-percent">{progress}%</span>
      </p>
      <Track project={project} />
      <dl className="project-facts">
        <div>
          <dt>Paid</dt>
          <dd>
            {money(project.paid_cents)} <span>/ {money(project.total_cents)}</span>
          </dd>
        </div>
        <div>
          <dt>Blocked</dt>
          <dd>{project.blocked === 0 ? "None" : `${project.blocked} milestone${project.blocked === 1 ? "" : "s"}`}</dd>
        </div>
      </dl>
      <div className="project-next">
        {project.next ? (
          <>
            <span>Next up</span>
            <strong>{project.next.name}</strong>
            <StatusChip status={project.next.status} quiet />
          </>
        ) : project.milestones === 0 ? (
          <span className="project-complete">No milestones yet.</span>
        ) : (
          <span className="project-complete">Every milestone is done.</span>
        )}
      </div>
      <a className="project-open" href={`#/projects/${project.id}`}>
        Open project <span aria-hidden="true">→</span>
      </a>
    </article>
  );
}

function SkeletonCard() {
  return (
    <article className="project-card skeleton-card" aria-hidden="true">
      <span className="skeleton skeleton-line short" />
      <span className="skeleton skeleton-line title" />
      <span className="skeleton skeleton-line" />
      <span className="skeleton skeleton-block" />
    </article>
  );
}

export function Board({ projects, loading, error, creating, createError, onCreate, onRetry }: Props) {
  const [name, setName] = useState("Juniper launch");

  const paid = projects?.reduce((sum, project) => sum + project.paid_cents, 0) ?? 0;
  const blocked = projects?.reduce((sum, project) => sum + project.blocked, 0) ?? 0;

  return (
    <>
      <section className="board-hero">
        <div>
          <p className="eyebrow">Freelance operations · human view</p>
          <h1>
            See what
            <br />
            depends on what.
          </h1>
        </div>
        <div className="board-hero-aside">
          <p className="lede">
            Milestones, invoices and sample payments in one graph. Read the dependency path,
            record a sample payment, and watch the unlock edge appear. No agent required.
          </p>
          <p className="hero-note">Sample money only. PayPal sandbox, no cards, no live money.</p>
        </div>
      </section>

      <section className="stat-strip" aria-label="Portfolio summary">
        <div className="stat">
          <span className="stat-value">{projects?.length ?? "–"}</span>
          <span className="stat-label">projects</span>
        </div>
        <div className="stat">
          <span className="stat-value">{blocked}</span>
          <span className="stat-label">blocked milestones</span>
        </div>
        <div className="stat">
          <span className="stat-value">{money(paid)}</span>
          <span className="stat-label">sample payments</span>
        </div>
        <div className="stat stat-quiet">
          <span className="stat-value">1 store</span>
          <span className="stat-label">humans and agents read the same graph</span>
        </div>
      </section>

      <section className="panel board-toolbar" aria-labelledby="create-title">
        <div>
          <p className="eyebrow">Write to the graph</p>
          <h2 id="create-title">Create a sample project</h2>
          <p className="toolbar-copy">
            Adds four milestones in a dependency chain, a paid scope invoice, one open invoice and
            one deliverable per milestone.
          </p>
        </div>
        <form
          className="create-form"
          onSubmit={(event) => {
            event.preventDefault();
            onCreate(name.trim() || "Juniper launch");
          }}
        >
          <label htmlFor="project-name">Project name</label>
          <div className="create-row">
            <input
              id="project-name"
              name="project-name"
              value={name}
              maxLength={80}
              onChange={(event) => setName(event.target.value)}
              placeholder="Juniper launch"
              autoComplete="off"
            />
            <button className="btn btn-primary" type="submit" disabled={creating}>
              {creating ? "Creating…" : "Create sample project"}
            </button>
          </div>
        </form>
      </section>

      {createError && (
        <p className="alert alert-error" role="alert">
          {createError}
        </p>
      )}

      <section className="board-panel" aria-labelledby="projects-title">
        <div className="section-head">
          <div>
            <p className="eyebrow">Portfolio</p>
            <h2 id="projects-title">Projects</h2>
          </div>
          <p className="section-count">{projects?.length ?? 0} in this store</p>
        </div>

        {error ? (
          <div className="empty-state" role="alert">
            <p className="empty-kicker">Graph unavailable</p>
            <h3>The projects could not be loaded.</h3>
            <p>{error}</p>
            <button className="btn btn-secondary" type="button" onClick={onRetry}>
              Try again
            </button>
          </div>
        ) : loading && !projects ? (
          <div className="project-grid" role="status" aria-live="polite" aria-busy="true">
            <span className="sr-only">Loading projects.</span>
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ) : projects && projects.length === 0 ? (
          <div className="empty-state">
            <p className="empty-kicker">Empty graph</p>
            <h3>No projects in this store yet.</h3>
            <p>Create the first sample project above to see a dependency chain and a blocked milestone.</p>
          </div>
        ) : (
          <div className="project-grid">
            {projects?.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>
        )}
      </section>
    </>
  );
}
