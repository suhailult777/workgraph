import { useEffect, useRef, useState, type FormEvent } from "react";
import { acceptPlan } from "../api";
import type { AppConfig } from "../types";

const SETUP_KEY = "workgraph-byok-setup-v1";
const DRAFT_KEY = "workgraph-plan-draft-v1";
const SAMPLES = [
  { label: "Decline path", prompt: "Which milestones are blocked until WG-1002 is paid?" },
  { label: "Paid design work", prompt: "Who has been paid for design-system work before?" },
  { label: "Draft a plan", prompt: "Draft a four-step plan for a new brand project." },
  { label: "Record payment", prompt: "Record the sample payment for WG-1002." },
  { label: "Card charge?", prompt: "Record a real card payment for the design system." },
];

type Setup = { baseUrl: string; key: string; model: string };

type Draft = {
  projectName?: string;
  brief?: string;
  milestones?: { name: string; depends_on?: string[] }[];
  similar_work?: { party?: string; project?: string; milestone?: string }[];
  note?: string;
};

type ConfirmItem = {
  action: string;
  description?: string;
  effect?: string;
  arguments?: Record<string, unknown>;
};

type ConfirmRequest = {
  items: ConfirmItem[];
  resolve: (approved: boolean) => void;
};

function readSetup(): Setup | null {
  try {
    const raw = sessionStorage.getItem(SETUP_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Setup>;
    if (!parsed.baseUrl || !parsed.key) return null;
    const check = validateRouter(String(parsed.baseUrl));
    if (!check.ok) {
      sessionStorage.removeItem(SETUP_KEY);
      return null;
    }
    return {
      baseUrl: check.url,
      key: String(parsed.key),
      model: String(parsed.model || "gpt-4.1-mini"),
    };
  } catch {
    return null;
  }
}

function isDraft(value: unknown): value is Draft {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  if (candidate.projectName !== undefined && typeof candidate.projectName !== "string") return false;
  if (candidate.note !== undefined && typeof candidate.note !== "string") return false;
  if (!Array.isArray(candidate.milestones)) return false;
  return candidate.milestones.every((milestone) => {
    if (!milestone || typeof milestone !== "object") return false;
    const item = milestone as Record<string, unknown>;
    if (typeof item.name !== "string" || !item.name.trim()) return false;
    if (item.depends_on === undefined) return true;
    return (
      Array.isArray(item.depends_on) &&
      item.depends_on.every((parent) => typeof parent === "string")
    );
  });
}

function readDraft(): Draft | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isDraft(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function isLoopbackHost(hostname: string): boolean {
  let host = hostname.toLowerCase().replace(/\.$/, "");
  if (host.startsWith("[") && host.endsWith("]")) host = host.slice(1, -1);
  if (host === "localhost" || host === "::1" || host === "0.0.0.0") return true;
  if (/^127\./.test(host)) return true;
  if (host.startsWith("::ffff:")) {
    const tail = host.slice("::ffff:".length);
    if (tail === "7f00:1" || tail === "127.0.0.1") return true;
  }
  return false;
}

function routerOriginKey(url: URL): string {
  const host = isLoopbackHost(url.hostname)
    ? "loopback"
    : url.hostname.toLowerCase().replace(/\.$/, "");
  return `${url.protocol}//${host}:${url.port}`;
}

function validateRouter(value: string): { ok: true; url: string } | { ok: false; reason: string } {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return { ok: false, reason: "Enter a full http(s) OpenAI-compatible base URL." };
  }
  if (!["http:", "https:"].includes(parsed.protocol)) {
    return { ok: false, reason: "The router must use http or https." };
  }
  if (parsed.username || parsed.password) {
    return { ok: false, reason: "Do not put a username or password in the router URL." };
  }
  if (parsed.search || parsed.hash) {
    return { ok: false, reason: "The router URL must not contain a query or fragment." };
  }
  if (parsed.pathname.replace(/\/$/, "").endsWith("/chat/completions")) {
    return { ok: false, reason: "Enter the router base URL, not the chat completions endpoint." };
  }
  if (routerOriginKey(parsed) === routerOriginKey(new URL(window.location.href))) {
    return {
      ok: false,
      reason: "That is this WorkGraph server. Use your own provider's base URL.",
    };
  }
  return { ok: true, url: parsed.href.replace(/\/+$/, "") };
}

function actionTitle(action: string): string {
  if (action === "accept_plan") return "Accept the plan and create the project";
  if (action === "record_payment") return "Record the sample payment";
  return action.replaceAll("_", " ");
}

function ConfirmDialog({
  request,
  onAnswer,
}: {
  request: ConfirmRequest;
  onAnswer: (approved: boolean) => void;
}) {
  return (
    <div className="assistant-confirm-backdrop">
      <div
        className="assistant-confirm"
        role="dialog"
        aria-modal="true"
        aria-labelledby="assistant-confirm-title"
      >
        <p className="eyebrow">Irreversible · review first</p>
        <h3 id="assistant-confirm-title">
          {request.items.length === 1
            ? actionTitle(request.items[0].action)
            : "Confirm these graph changes"}
        </h3>
        {request.items.map((item) => {
          const args = item.arguments || {};
          const milestones = Array.isArray(args.milestones) ? args.milestones : [];
          return (
            <div className="assistant-confirm-item" key={item.action}>
              {item.description && <p className="assistant-confirm-desc">{item.description}</p>}
              {typeof args.projectName === "string" && (
                <p>
                  Project: <strong>{args.projectName}</strong>
                </p>
              )}
              {milestones.length > 0 && (
                <ol className="assistant-confirm-plan">
                  {milestones.map((step) => {
                    const record = step as { name?: string; depends_on?: string[] };
                    return (
                      <li key={record.name}>
                        <strong>{record.name}</strong>
                        {record.depends_on?.length
                          ? ` after ${record.depends_on.join(", ")}`
                          : " first"}
                      </li>
                    );
                  })}
                </ol>
              )}
              {typeof args.invoiceId === "string" && (
                <p>
                  Invoice id: <code>{args.invoiceId}</code>
                </p>
              )}
              {typeof args.amountCents === "number" && (
                <p>
                  Amount: <strong>{args.amountCents.toLocaleString("en-US")} integer cents</strong>
                </p>
              )}
            </div>
          );
        })}
        <p className="assistant-confirm-note">
          The graph changes only after you confirm. Cancel leaves it exactly as it is.
        </p>
        <div className="assistant-confirm-actions">
          <button
            className="btn btn-secondary"
            type="button"
            onClick={() => onAnswer(false)}
          >
            Cancel · change nothing
          </button>
          <button
            className="btn btn-primary"
            type="button"
            autoFocus
            onClick={() => onAnswer(true)}
          >
            Confirm and write
          </button>
        </div>
      </div>
    </div>
  );
}

export function AssistantPanel({ config }: { config: AppConfig | null }) {
  const [setup] = useState<Setup | null>(() => readSetup());
  const [baseUrl, setBaseUrl] = useState(setup?.baseUrl ?? "");
  const [model, setModel] = useState(setup?.model ?? "gpt-4.1-mini");
  const [key, setKey] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [bootMessage, setBootMessage] = useState("Connecting the assistant…");
  const [bootOk, setBootOk] = useState<boolean | null>(null);
  const [bootAttempt, setBootAttempt] = useState(0);
  const [draft, setDraft] = useState<Draft | null>(() => readDraft());
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const hasKey = Boolean(setup?.key && setup?.baseUrl);
  const live = Boolean(config?.assistant_live);
  const production = config?.environment === "production";

  function requestConfirmation(items: ConfirmItem[]): Promise<boolean> {
    return new Promise((resolve) => {
      setConfirmRequest({ items, resolve });
    });
  }

  function answerConfirmation(approved: boolean) {
    const current = confirmRequest;
    setConfirmRequest(null);
    current?.resolve(approved);
  }

  useEffect(() => {
    const onDraft = (event: Event) => {
      const detail = (event as CustomEvent<unknown>).detail;
      if (isDraft(detail)) setDraft(detail);
    };
    window.addEventListener("workgraph:draft", onDraft);
    return () => window.removeEventListener("workgraph:draft", onDraft);
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || host.dataset.workgraphAssistant) return;
    if (!config && !hasKey) {
      setBootOk(null);
      setBootMessage("Checking assistant configuration…");
      return;
    }
    if (!hasKey && production && !live) {
      setBootOk(false);
      setBootMessage(
        "The live assistant is not configured on this deployment. No demo fallback runs in production.",
      );
      return;
    }
    host.dataset.workgraphAssistant = "booting";
    host.innerHTML = `
      <div id="agent-app" class="assistant-runtime">
        <div data-ns-slot="header"></div>
        <div class="assistant-panels">
          <div data-ns-slot="chat"></div>
          <div data-ns-slot="agents"></div>
        </div>
        <div data-ns-slot="settings" class="assistant-settings-slot"></div>
      </div>`;

    const bootAssistant = async () => {
      try {
        const runtimeUrl = "/runtime/index.js";
        const runtime = (await import(/* @vite-ignore */ runtimeUrl)) as {
          boot: (
            root: Element,
            options: Record<string, unknown>,
          ) => Promise<{
            engine: { onActionConfirm: (items: unknown) => Promise<boolean> };
          }>;
        };
        const root = host.querySelector("#agent-app");
        if (!root) throw new Error("Assistant mount is missing.");
        const router = hasKey ? setup?.baseUrl : live ? "/api/assistant" : "/api/demo/llm";
        const byokKey = hasKey ? setup?.key : live ? "server" : "local-demo";
        let selectedModel = hasKey ? setup?.model || "gpt-4.1-mini" : live ? "server" : " ";
        if (!hasKey && live) {
          try {
            const response = await fetch("/api/assistant/models", { cache: "no-store" });
            const body = await response.json();
            const first = Array.isArray(body?.data) ? body.data[0]?.id : "";
            if (first) selectedModel = String(first);
          } catch {
            // The runtime falls back to the server's first allowlisted model.
          }
        }
        const { engine } = await runtime.boot(root, {
          originUrl: new URL("/", window.location.href).href,
          sandboxWorkerUrl: new URL("/runtime/sandbox-worker.js", window.location.href).href,
          byokKey,
          router,
          model: selectedModel,
          runner: "manual",
        });
        engine.onActionConfirm = (items: unknown) =>
          requestConfirmation(Array.isArray(items) ? (items as ConfirmItem[]) : []);
        const hiddenKey = host.querySelector<HTMLInputElement>("#ns-key");
        if (hiddenKey) hiddenKey.value = "";
        (window as unknown as { __workgraphAssistant?: unknown }).__workgraphAssistant = engine;
        const greeting =
          "I read the same sample graph as the page. Ask me which milestones are blocked, " +
          "who was paid for a skill, or for a plan. I can accept a plan or record a sample " +
          "payment after you confirm the dialog. I cannot charge a card, take real money or send email.";
        const first = host.querySelector("#ns-msgs .ns-msg.bot");
        if (first) first.textContent = greeting;
        setBootOk(true);
        setBootMessage(
          hasKey
            ? `Your key is loaded in this tab and is sent only to ${setup?.baseUrl}.`
            : live
              ? "Live assistant connected. It uses a free server-side model and the same graph."
              : "Local demo model connected. This is a development fallback, not production.",
        );
      } catch (error) {
        const hiddenKey = host.querySelector<HTMLInputElement>("#ns-key");
        if (hiddenKey) hiddenKey.value = "";
        setBootOk(false);
        setBootMessage("The assistant could not load. The page, graph and sample payments still work.");
        console.error("WorkGraph assistant failed to boot", error);
      }
    };
    void bootAssistant();
  }, [hasKey, setup, bootAttempt, live, production, config]);

  function retryBoot() {
    const host = hostRef.current;
    if (host) {
      delete host.dataset.workgraphAssistant;
      host.innerHTML = "";
    }
    setBootOk(null);
    setBootMessage("Connecting the assistant…");
    setBootAttempt((attempt) => attempt + 1);
  }

  function applyKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const check = validateRouter(baseUrl.trim());
    if (!check.ok) {
      setFormError(check.reason);
      return;
    }
    if (!key.trim()) {
      setFormError("Enter a key, or keep using the server assistant.");
      return;
    }
    const next: Setup = {
      baseUrl: check.url,
      key: key.trim(),
      model: model.trim() || "gpt-4.1-mini",
    };
    try {
      sessionStorage.setItem(SETUP_KEY, JSON.stringify(next));
      window.location.reload();
    } catch {
      setFormError("This browser cannot keep a tab-only key.");
    }
  }

  function useDefault() {
    try {
      sessionStorage.removeItem(SETUP_KEY);
      window.location.reload();
    } catch {
      setFormError("This browser cannot clear the tab setup.");
    }
  }

  function clearDraft() {
    try {
      sessionStorage.removeItem(DRAFT_KEY);
    } catch {
      // The visible draft still clears.
    }
    setDraft(null);
  }

  async function acceptDraft() {
    if (!draft) return;
    const milestones = (draft.milestones ?? []).map((milestone) => ({
      name: milestone.name,
      depends_on: milestone.depends_on ?? [],
    }));
    const approved = await requestConfirmation([
      {
        action: "accept_plan",
        description:
          "Create the four-step sample project. The server assigns the sample amounts; no real money moves.",
        arguments: { projectName: draft.projectName || "New project", milestones },
      },
    ]);
    if (!approved) {
      setActionMessage("Plan not accepted. The graph is unchanged.");
      return;
    }
    setActionMessage("Creating the project…");
    try {
      const result = await acceptPlan(draft.projectName || "New project", milestones);
      clearDraft();
      setActionMessage(
        `Accepted ${result.project.project.name} [${result.project.project.id}]. The board now has it.`,
      );
      window.dispatchEvent(new Event("workgraph:graph"));
    } catch (reason) {
      setActionMessage(
        reason instanceof Error ? reason.message : "The plan could not be accepted.",
      );
    }
  }

  function askSample(prompt: string) {
    const input = hostRef.current?.querySelector<HTMLInputElement>("#ns-input");
    const send = hostRef.current?.querySelector<HTMLButtonElement>("#ns-send");
    if (!input || !send || input.disabled || send.disabled) return;
    input.value = prompt;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    send.click();
  }

  const modeLabel = hasKey
    ? "Your router"
    : live
      ? "Live server"
      : production
        ? "Not configured"
        : "Local demo";
  const modeClass = hasKey || live ? "is-live" : production ? "is-missing" : "is-demo";

  return (
    <section id="assistant" className="assistant-section" aria-labelledby="assistant-title">
      <div className="assistant-heading">
        <div>
          <p className="eyebrow">Agentic Web · runs in your browser</p>
          <h2 id="assistant-title">Ask the graph</h2>
          <p className="assistant-lede">
            The assistant reads the same projects, blocked paths and sample payments as the page.
            It can accept a plan or record a sample payment after you confirm the dialog. It never
            charges a card, sends email or moves real money.
          </p>
        </div>
        <div className="assistant-mode-box">
          <span className={`assistant-mode ${modeClass}`}>
            <span className="assistant-mode-dot" aria-hidden="true" />
            {modeLabel}
          </span>
          <span className="assistant-mode-note">
            {hasKey
              ? "Key kept in this tab"
              : live
                ? "Free server model"
                : production
                  ? "Set OPENROUTER_API_KEY"
                  : "No key needed"}
          </span>
        </div>
      </div>

      <p id="assistant-status" className={`assistant-status${bootOk === false ? " is-error" : ""}`} role="status">
        {bootMessage}
      </p>
      {bootOk === false && (
        <button className="btn btn-secondary btn-small assistant-retry" type="button" onClick={retryBoot}>
          Retry assistant
        </button>
      )}

      <div className="assistant-samples" aria-label="Try a sample question">
        <span>Try</span>
        {SAMPLES.map((sample) => (
          <button
            key={sample.label}
            type="button"
            className="assistant-sample"
            onClick={() => askSample(sample.prompt)}
          >
            {sample.label}
          </button>
        ))}
      </div>

      <div className="assistant-shell">
        <div className="assistant-live" ref={hostRef} role="region" aria-label="WorkGraph assistant" />

        <aside className="assistant-aside" aria-label="Assistant settings and limits">
          <section className="assistant-card" aria-labelledby="byok-title">
            <p className="eyebrow">Bring your own key</p>
            <h3 id="byok-title">Use your own router</h3>
            <p className="assistant-card-copy">
              The live server assistant is the default when configured. A real key here stays in
              this tab's sessionStorage and is sent only to the router you choose. WorkGraph's
              server never receives it.
            </p>
            {hasKey ? (
              <div className="byok-loaded">
                <dl>
                  <div>
                    <dt>Router</dt>
                    <dd>{setup?.baseUrl}</dd>
                  </div>
                  <div>
                    <dt>Model</dt>
                    <dd>{setup?.model}</dd>
                  </div>
                  <div>
                    <dt>Key</dt>
                    <dd>Loaded in this tab, not shown</dd>
                  </div>
                </dl>
                <div className="byok-actions">
                  <button className="btn btn-secondary btn-small" type="button" onClick={useDefault}>
                    Forget key and use the default
                  </button>
                </div>
              </div>
            ) : (
              <form className="byok-form" onSubmit={applyKey}>
                <label htmlFor="byok-base">Base URL</label>
                <input
                  id="byok-base"
                  type="url"
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                  placeholder="https://openrouter.ai/api/v1"
                  autoComplete="off"
                  spellCheck={false}
                />
                <label htmlFor="byok-model">Model</label>
                <input
                  id="byok-model"
                  type="text"
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  placeholder="gpt-4.1-mini"
                  autoComplete="off"
                  spellCheck={false}
                />
                <label htmlFor="byok-key">API key</label>
                <input
                  id="byok-key"
                  type="password"
                  value={key}
                  onChange={(event) => setKey(event.target.value)}
                  placeholder="Your key, kept in this tab only"
                  autoComplete="off"
                  spellCheck={false}
                />
                {formError && (
                  <p className="byok-error" role="alert">
                    {formError}
                  </p>
                )}
                <div className="byok-actions">
                  <button className="btn btn-primary btn-small" type="submit">
                    Use this key
                  </button>
                  <button className="btn btn-secondary btn-small" type="button" onClick={useDefault}>
                    Use default
                  </button>
                </div>
                <p className="byok-fineprint">
                  No key is written to the repo, the graph or a WorkGraph request. Closing the tab
                  clears the tab setup.
                </p>
              </form>
            )}
          </section>

          <section className="assistant-card assistant-limits" aria-labelledby="limits-title">
            <p className="eyebrow">Confirmed writes</p>
            <h3 id="limits-title">What it can do</h3>
            <ul>
              <li>Read projects, milestone ids, blocked paths, invoices and sample payments.</li>
              <li>Trace every milestone blocked until one invoice is paid.</li>
              <li>Draft a four-step plan, then accept it after you confirm.</li>
              <li>Record one sample payment for the exact invoice amount after you confirm.</li>
            </ul>
            <p className="assistant-card-copy">
              Cancel leaves the graph unchanged. The assistant cannot charge a card, take real
              money, send email or call live PayPal. PayPal sandbox checkout is a separate button
              on the project page.
            </p>
          </section>

          {draft && (
            <section className="assistant-card assistant-draft" aria-labelledby="draft-title">
              <p className="eyebrow">Local draft</p>
              <h3 id="draft-title">{draft.projectName || "Draft project"}</h3>
              <ol>
                {(draft.milestones ?? []).map((milestone) => (
                  <li key={milestone.name}>
                    <strong>{milestone.name}</strong>
                    {milestone.depends_on?.length ? (
                      <span> after {milestone.depends_on.join(", ")}</span>
                    ) : (
                      <span> first</span>
                    )}
                  </li>
                ))}
              </ol>
              <p className="assistant-card-copy">
                {draft.note ||
                  "Saved in this tab only. The graph did not change. Accept it only after you review the dialog."}
              </p>
              <div className="byok-actions">
                <button className="btn btn-primary btn-small" type="button" onClick={acceptDraft}>
                  Accept plan
                </button>
                <button className="btn btn-secondary btn-small" type="button" onClick={clearDraft}>
                  Clear draft
                </button>
              </div>
              {actionMessage && (
                <p className="assistant-card-copy" role="status">
                  {actionMessage}
                </p>
              )}
            </section>
          )}
        </aside>
      </div>

      {confirmRequest && (
        <ConfirmDialog request={confirmRequest} onAnswer={answerConfirmation} />
      )}
    </section>
  );
}
