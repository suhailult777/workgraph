import { useEffect, useRef, useState, type FormEvent } from "react";

const SETUP_KEY = "workgraph-byok-setup-v1";
const DRAFT_KEY = "workgraph-plan-draft-v1";
const SAMPLES = [
  { label: "Blocked milestones", prompt: "Which milestones are blocked by an unpaid invoice?" },
  { label: "Paid design work", prompt: "Who has been paid for design-system work before?" },
  { label: "Draft a plan", prompt: "Draft a four-step plan for a new brand project." },
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

export function AssistantPanel() {
  const [setup] = useState<Setup | null>(() => readSetup());
  const [baseUrl, setBaseUrl] = useState(setup?.baseUrl ?? "");
  const [model, setModel] = useState(setup?.model ?? "gpt-4.1-mini");
  const [key, setKey] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [bootMessage, setBootMessage] = useState("Connecting the assistant…");
  const [bootOk, setBootOk] = useState<boolean | null>(null);
  const [bootAttempt, setBootAttempt] = useState(0);
  const [draft, setDraft] = useState<Draft | null>(() => readDraft());
  const hostRef = useRef<HTMLDivElement>(null);
  const hasKey = Boolean(setup?.key && setup?.baseUrl);

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
        const { engine } = await runtime.boot(root, {
          originUrl: new URL("/", window.location.href).href,
          sandboxWorkerUrl: new URL("/runtime/sandbox-worker.js", window.location.href).href,
          byokKey: hasKey ? setup?.key : "demo",
          router: hasKey ? setup?.baseUrl : "/api/demo/llm",
          // A blank model keeps the runtime on the published mock router. A real model
          // name makes selectTopRouter upgrade to byok_router even without a key.
          model: hasKey ? setup?.model || "gpt-4.1-mini" : " ",
          runner: "manual",
        });
        // The runtime's own settings panel is hidden; clear any saved profile it copied
        // into its key field so a pre-existing nsDeploy key is not left in the DOM.
        const hiddenKey = host.querySelector<HTMLInputElement>("#ns-key");
        if (hiddenKey) hiddenKey.value = "";
        (window as unknown as { __workgraphAssistant?: unknown }).__workgraphAssistant = engine;
        const greeting =
          "I read the same sample graph as the page. Ask me which milestones are blocked, " +
          "who was paid for a skill, or for a draft milestone plan. I cannot charge a card, " +
          "take real money, send email or write the graph.";
        const first = host.querySelector("#ns-msgs .ns-msg.bot");
        if (first) first.textContent = greeting;
        setBootOk(true);
        setBootMessage(
          hasKey
            ? `Your key is loaded in this tab and is sent only to ${setup?.baseUrl}.`
            : "Demo model connected. No key is needed. Every answer comes from the sample graph.",
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
  }, [hasKey, setup, bootAttempt]);

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
      setFormError("Enter a key, or keep using the demo model.");
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

  function useDemo() {
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

  function askSample(prompt: string) {
    const input = hostRef.current?.querySelector<HTMLInputElement>("#ns-input");
    const send = hostRef.current?.querySelector<HTMLButtonElement>("#ns-send");
    if (!input || !send || input.disabled || send.disabled) return;
    input.value = prompt;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    send.click();
  }

  return (
    <section id="assistant" className="assistant-section" aria-labelledby="assistant-title">
      <div className="assistant-heading">
        <div>
          <p className="eyebrow">Agentic Web · runs in your browser</p>
          <h2 id="assistant-title">Ask the graph</h2>
          <p className="assistant-lede">
            The assistant reads the same projects, blocked paths and sample payments as the page.
            It can draft a plan. It cannot charge a card, send email or write the graph.
          </p>
        </div>
        <div className="assistant-mode-box">
          <span className={`assistant-mode ${hasKey ? "is-live" : "is-demo"}`}>
            <span className="assistant-mode-dot" aria-hidden="true" />
            {hasKey ? "Your router" : "Demo model"}
          </span>
          <span className="assistant-mode-note">
            {hasKey ? "Key kept in this tab" : "No key needed"}
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
              The demo model needs no key. A real key stays in this tab's sessionStorage and is
              sent only to the router you choose. WorkGraph's server never receives it.
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
                  <button className="btn btn-secondary btn-small" type="button" onClick={useDemo}>
                    Forget key and use demo
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
                  <button className="btn btn-secondary btn-small" type="button" onClick={useDemo}>
                    Demo mode
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
            <p className="eyebrow">This milestone</p>
            <h3 id="limits-title">What it can do</h3>
            <ul>
              <li>Read projects, milestone statuses, blocked paths, invoices and sample payments.</li>
              <li>Find paid work by a skill through the graph traversal.</li>
              <li>Draft a four-step plan in this tab. No amounts, no graph write.</li>
            </ul>
            <p className="assistant-card-copy">
              It cannot accept a plan, record a sample payment, unlock a deliverable, charge a
              card, take real money, send email or call live PayPal. Use the project page for
              sample payments.
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
                  "Saved in this tab only. The graph did not change. Accepting a plan is not available yet."}
              </p>
              <button className="btn btn-secondary btn-small" type="button" onClick={clearDraft}>
                Clear draft
              </button>
            </section>
          )}
        </aside>
      </div>
    </section>
  );
}
