import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  capturePayPalOrder,
  completeMilestone,
  createSampleProject,
  getConfig,
  getHealth,
  getProject,
  getProjects,
  money,
} from "./api";
import { Board } from "./components/Board";
import { PaymentDialog } from "./components/PaymentDialog";
import { ProjectView } from "./components/ProjectView";
import { AssistantPanel } from "./components/AssistantPanel";
import type {
  AppConfig,
  Health,
  Milestone,
  PaymentResult,
  ProjectDetail,
  ProjectSummary,
} from "./types";

type Route = { view: "board" } | { view: "project"; id: string } | { view: "paypal"; orderId: string };

function parseHash(): Route {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const match = hash.match(/^projects\/([^/]+)$/);
  if (match) {
    try {
      return { view: "project", id: decodeURIComponent(match[1]) };
    } catch {
      return { view: "board" };
    }
  }
  return { view: "board" };
}

function parseInitialRoute(): Route {
  const path = window.location.pathname.replace(/\/+$/, "");
  if (path === "/paypal/return") {
    return {
      view: "paypal",
      orderId: new URLSearchParams(window.location.search).get("token") || "",
    };
  }
  return parseHash();
}

function messageOf(reason: unknown): string {
  return reason instanceof ApiError ? reason.message : "Something went wrong. Try again.";
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseInitialRoute());
  const [health, setHealth] = useState<Health | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [paypalReturn, setPaypalReturn] = useState<{
    status: "capturing" | "done" | "error";
    message: string;
    projectId?: string;
  }>({
    status: "capturing",
    message: "Checking the PayPal return…",
  });

  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [projectsVersion, setProjectsVersion] = useState(0);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [projectLoading, setProjectLoading] = useState(false);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [projectVersion, setProjectVersion] = useState(0);
  const [actionError, setActionError] = useState<string | null>(null);
  const [completingId, setCompletingId] = useState<string | null>(null);

  const [payInvoiceId, setPayInvoiceId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const creatingRef = useRef(false);
  const projectIdRef = useRef<string | null>(null);

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
    getConfig()
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);

  useEffect(() => {
    const onGraphChanged = () => {
      setProjectsVersion((version) => version + 1);
      setProjectVersion((version) => version + 1);
    };
    window.addEventListener("workgraph:graph", onGraphChanged);
    return () => window.removeEventListener("workgraph:graph", onGraphChanged);
  }, []);

  useEffect(() => {
    if (route.view !== "paypal") return;
    let live = true;
    if (!route.orderId) {
      setPaypalReturn({
        status: "error",
        message:
          "PayPal returned without an order token. Open the project and start the sandbox checkout again.",
      });
      return;
    }
    setPaypalReturn({
      status: "capturing",
      message: "PayPal approved the order. Verifying the sandbox capture and recording one payment…",
    });
    capturePayPalOrder(route.orderId)
      .then((result) => {
        if (!live) return;
        if (result.payment) {
          const projectId = result.payment.project.project.id;
          window.history.replaceState({}, "", `/#/projects/${projectId}`);
          handlePaid(result.payment);
          setPaypalReturn({
            status: "done",
            projectId,
            message: result.already_captured
              ? "This PayPal order was already captured. No second payment was recorded."
              : `Sandbox capture ${result.capture_id || ""} recorded. The invoice is paid and the deliverable is unlocked.`,
          });
          setRoute({ view: "project", id: projectId });
          return;
        }
        setPaypalReturn({
          status: result.already_captured ? "done" : "error",
          message: result.already_captured
            ? "This order was already captured. The graph already has its payment."
            : "The sandbox capture completed, but the graph returned no payment payload.",
        });
      })
      .catch((reason: unknown) => {
        if (!live) return;
        setPaypalReturn({
          status: "error",
          message: `${messageOf(reason)} Open the project and retry the capture if PayPal shows the order as approved.`,
        });
      });
    return () => {
      live = false;
    };
  }, [route]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [route]);

  useEffect(() => {
    if (route.view !== "board") return;
    let live = true;
    setProjectsLoading(true);
    setProjectsError(null);
    getProjects()
      .then((data) => live && setProjects(data.projects))
      .catch((reason: unknown) => live && setProjectsError(messageOf(reason)))
      .finally(() => live && setProjectsLoading(false));
    return () => {
      live = false;
    };
  }, [route.view, projectsVersion]);

  const projectId = route.view === "project" ? route.id : null;
  useEffect(() => {
    projectIdRef.current = projectId;
  }, [projectId]);

  useEffect(() => {
    setPayInvoiceId(null);
  }, [route]);

  useEffect(() => {
    if (!projectId) return;
    let live = true;
    setProject(null);
    setProjectError(null);
    setActionError(null);
    setProjectLoading(true);
    getProject(projectId)
      .then((data) => live && setProject(data))
      .catch((reason: unknown) => live && setProjectError(messageOf(reason)))
      .finally(() => live && setProjectLoading(false));
    return () => {
      live = false;
    };
  }, [projectId, projectVersion]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 8000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  function navigateTo(path: string) {
    window.location.hash = path;
  }

  async function handleCreate(name: string) {
    if (creatingRef.current) return;
    creatingRef.current = true;
    setCreating(true);
    setCreateError(null);
    try {
      const created = await createSampleProject(name);
      setCreateError(null);
      navigateTo(`/projects/${created.project.id}`);
    } catch (reason) {
      setCreateError(messageOf(reason));
    } finally {
      creatingRef.current = false;
      setCreating(false);
    }
  }

  const closeDialog = useCallback(() => setPayInvoiceId(null), []);

  function handlePaid(result: PaymentResult) {
    setPayInvoiceId(null);
    setProjectsVersion((version) => version + 1);
    setActionError(null);
    const names = result.unlocked.map((deliverable) => deliverable.name).join(", ");
    setToast(
      `Payment of ${money(result.amount_cents)} recorded. ${names || "Deliverable"} unlocked.`,
    );
    if (projectIdRef.current !== result.project.project.id) {
      setProjectVersion((version) => version + 1);
      return;
    }
    setProject(result.project);
  }

  async function handleComplete(milestone: Milestone) {
    const targetProject = projectIdRef.current;
    if (!targetProject) return;
    setCompletingId(milestone.id);
    setActionError(null);
    try {
      const updated = await completeMilestone(milestone.id);
      if (projectIdRef.current !== targetProject) {
        setProjectVersion((version) => version + 1);
        return;
      }
      setProject(updated);
      setToast(`${milestone.name} marked done. Downstream milestones recalculated.`);
    } catch (reason) {
      if (projectIdRef.current === targetProject) {
        setActionError(messageOf(reason));
      }
    } finally {
      setCompletingId(null);
    }
  }

  const storeLabel = health?.store ?? "data/workgraph.rl";
  const healthLabel = useMemo(() => {
    if (!health) return "Checking graph";
    return health.graph_ready ? "Graph ready" : "Graph missing";
  }, [health]);
  const envBadge = !config
    ? "CHECKING"
    : config.assistant_live
      ? "LIVE"
      : config.environment === "production"
        ? "NOT CONFIGURED"
        : "DEV";
  const envClass = !config
    ? "is-checking"
    : config.assistant_live
      ? "is-live"
      : config.environment === "production"
        ? "is-missing"
        : "is-dev";

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <a className="brand" href="#/" aria-label="WorkGraph home">
          <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M8 9 L23 7 M8 9 L17 24 M23 7 L17 24" />
            <circle cx="8" cy="9" r="3" />
            <circle cx="23" cy="7" r="3" />
            <circle cx="17" cy="24" r="3" />
          </svg>
          <span>WorkGraph</span>
        </a>
        <div className="topbar-right">
          <button
            className="topbar-ask"
            type="button"
            aria-label="Ask the graph assistant"
            onClick={() =>
              document.getElementById("assistant")?.scrollIntoView({ behavior: "smooth", block: "start" })
            }
          >
            Ask
          </button>
          <span className={`env-badge ${envClass}`} title="Assistant mode">
            {envBadge}
          </span>
          <span className={`live-dot${health?.graph_ready ? " is-ready" : ""}`} aria-hidden="true" />
          <span className="topbar-status">{healthLabel}</span>
          <span className="topbar-divider" aria-hidden="true" />
          <span className="topbar-store">{storeLabel}</span>
        </div>
      </header>

      <main id="main" className="app">
        {route.view === "paypal" ? (
          <section className="empty-state paypal-return" aria-live="polite">
            <p className="empty-kicker">PayPal sandbox return</p>
            <h1>
              {paypalReturn.status === "capturing"
                ? "Verifying the capture…"
                : paypalReturn.status === "done"
                  ? "Payment recorded"
                  : "Capture needs attention"}
            </h1>
            <p>{paypalReturn.message}</p>
            {paypalReturn.status === "capturing" ? (
              <p className="paypal-return-note">
                Do not close this tab. The server checks the PayPal sandbox order, the amount and
                the currency before it writes one ledger payment.
              </p>
            ) : (
              <div className="empty-actions">
                {paypalReturn.projectId ? (
                  <button
                    className="btn btn-primary"
                    type="button"
                    onClick={() => navigateTo(`/projects/${paypalReturn.projectId}`)}
                  >
                    Open the paid project
                  </button>
                ) : null}
                <button
                  className="btn btn-secondary"
                  type="button"
                  onClick={() => {
                    window.history.replaceState({}, "", "/#/");
                    setRoute({ view: "board" });
                  }}
                >
                  Back to projects
                </button>
              </div>
            )}
          </section>
        ) : route.view === "board" ? (
          <Board
            projects={projects}
            loading={projectsLoading}
            error={projectsError}
            creating={creating}
            createError={createError}
            onCreate={handleCreate}
            onRetry={() => setProjectsVersion((version) => version + 1)}
          />
        ) : (
          <ProjectView
            project={project}
            loading={projectLoading}
            error={projectError}
            actionError={actionError}
            completingId={completingId}
            storeLabel={storeLabel}
            onBack={() => navigateTo("/")}
            onRetry={() => setProjectVersion((version) => version + 1)}
            onRecordPayment={setPayInvoiceId}
            onComplete={handleComplete}
            onDismissActionError={() => setActionError(null)}
          />
        )}
      </main>

      <AssistantPanel config={config} />

      <footer className="site-footer">
        <p>
          Sample ledger only. No cards, no real money. The live assistant uses a free
          server-side model when configured; the local no-key demo is a development fallback.
          PayPal is sandbox only. Amounts are integer cents.
        </p>
        <nav aria-label="Agent artifacts">
          <a href="/agent-manifest.json">agent manifest</a>
          <a href="/workgraph.network.json">agent network</a>
          <a href="#/">projects</a>
        </nav>
      </footer>

      {payInvoiceId && (
        <PaymentDialog invoiceId={payInvoiceId} onClose={closeDialog} onPaid={handlePaid} />
      )}

      {toast && (
        <div className="toast" role="status" aria-live="polite">
          <span>{toast}</span>
          <button type="button" onClick={() => setToast(null)} aria-label="Dismiss message">
            ×
          </button>
        </div>
      )}
    </>
  );
}
