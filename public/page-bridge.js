// Shared browser-side operations for the WorkGraph assistant.
// Reads use the same public API as the React page. The draft is kept in
// sessionStorage only and never written to the graph.

const STATE_URL = "/api/graph/state";
const SIMILAR_URL = "/api/graph/similar";
const DECLINE_URL = "/api/graph/decline-path";
const ACCEPT_PLAN_URL = "/api/plans/accept";
const PAYMENTS_URL = "/api/payments";
const PAYPAL_ORDER_URL = "/api/paypal/orders";
const DRAFT_KEY = "workgraph-plan-draft-v1";

async function getJson(url) {
  let response;
  try {
    response = await fetch(url, { headers: { accept: "application/json" } });
  } catch {
    return { ok: false, reason: "Could not reach the local graph service." };
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    const reason =
      (typeof detail === "string" ? detail : detail?.message) ||
      `The graph service answered ${response.status}.`;
    return { ok: false, reason, code: detail?.code };
  }
  return body;
}

async function postJson(url, payload) {
  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    return { ok: false, reason: "Could not reach the local graph service." };
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    const reason =
      (typeof detail === "string" ? detail : detail?.message) ||
      `The graph service answered ${response.status}.`;
    return { ok: false, reason, code: detail?.code };
  }
  return body;
}

function planTemplate() {
  return [
    { name: "Scope", depends_on: [] },
    { name: "Design", depends_on: ["Scope"] },
    { name: "Build", depends_on: ["Design"] },
    { name: "Handover", depends_on: ["Build"] },
  ];
}

function skillInBrief(brief, skills) {
  const lower = brief.toLowerCase();
  for (const skill of skills) {
    const name = String(skill);
    const words = name.toLowerCase().split(/\s+/);
    if (lower.includes(name.toLowerCase()) || words.every((word) => lower.includes(word))) {
      return name;
    }
  }
  if (/design|brand/.test(lower)) return "Design systems";
  if (/research|interview/.test(lower)) return "User research";
  if (/front.?end|build|website/.test(lower)) return "Front-end build";
  return null;
}

export class WorkGraphPage {
  static async getGraphState() {
    const state = await getJson(STATE_URL);
    if (state.ok === false) return state;
    return { ok: true, ...state };
  }

  static async searchSimilarWork(skill) {
    const body = await getJson(`${SIMILAR_URL}?skill=${encodeURIComponent(skill)}`);
    if (body.ok === false) return body;
    return { ok: true, skill: body.skill, work: body.work || [] };
  }

  static async getDeclinePath(invoiceNumber) {
    const number = String(invoiceNumber || "").trim();
    if (!number) {
      return { ok: false, reason: "An invoice number is required.", field: "invoice" };
    }
    const body = await getJson(`${DECLINE_URL}?invoice=${encodeURIComponent(number)}`);
    if (body.ok === false) return body;
    return { ok: true, ...body };
  }

  static async acceptPlan({ projectName, milestones } = {}) {
    const name = String(projectName || "").trim().slice(0, 80);
    if (!name) {
      return { ok: false, reason: "A project name is required.", field: "projectName" };
    }
    const plan = Array.isArray(milestones) && milestones.length ? milestones : planTemplate();
    const body = await postJson(ACCEPT_PLAN_URL, {
      project_name: name,
      milestones: plan.map((step) => ({
        name: String(step.name || "").trim(),
        depends_on: Array.isArray(step.depends_on) ? step.depends_on.map(String) : [],
      })),
    });
    if (body.ok === false) return body;
    return { ok: true, ...body };
  }

  static async recordPayment({ invoiceId, amountCents } = {}) {
    const invoice = String(invoiceId || "").trim();
    if (!invoice) {
      return { ok: false, reason: "An invoice id is required.", field: "invoiceId" };
    }
    if (!Number.isInteger(amountCents) || amountCents <= 0) {
      return {
        ok: false,
        reason: "The exact invoice amount in integer cents is required.",
        field: "amountCents",
      };
    }
    const body = await postJson(PAYMENTS_URL, {
      invoice_id: invoice,
      amount_cents: amountCents,
    });
    if (body.ok === false) return body;
    return { ok: true, ...body };
  }

  static async createPayPalOrder(invoiceId) {
    const invoice = String(invoiceId || "").trim();
    if (!invoice) {
      return { ok: false, reason: "An invoice id is required.", field: "invoiceId" };
    }
    const body = await postJson(PAYPAL_ORDER_URL, { invoice_id: invoice });
    if (body.ok === false) return body;
    return { ok: true, ...body };
  }

  static async capturePayPalOrder(orderId) {
    const order = String(orderId || "").trim();
    if (!order) {
      return { ok: false, reason: "A PayPal order id is required.", field: "orderId" };
    }
    const body = await postJson(`${PAYPAL_ORDER_URL}/${encodeURIComponent(order)}/capture`, {});
    if (body.ok === false) return body;
    return { ok: true, ...body };
  }

  static async proposePlan({ brief, projectName } = {}) {
    const text = String(brief || "").trim();
    if (!text) {
      return { ok: false, reason: "A short project brief is required.", field: "brief" };
    }
    if (text.length > 600) {
      return { ok: false, reason: "The brief must be 600 characters or fewer.", field: "brief" };
    }
    const name = String(projectName || "").trim().slice(0, 80) || "Draft project";

    const state = await WorkGraphPage.getGraphState();
    if (state.ok === false) return state;

    const skill = skillInBrief(text, state.skills || []);
    let similar = [];
    if (skill) {
      const result = await WorkGraphPage.searchSimilarWork(skill);
      if (result.ok !== false) similar = result.work;
    }

    return {
      ok: true,
      draft: true,
      brief: text,
      projectName: name,
      milestones: planTemplate(),
      similar_work: similar,
      note:
        "Draft only. No amounts are proposed and the graph is not changed. " +
        "Review it and confirm before accepting; cancel changes nothing.",
    };
  }

  static readDraft() {
    try {
      const raw = sessionStorage.getItem(DRAFT_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  static clearDraft() {
    try {
      sessionStorage.removeItem(DRAFT_KEY);
      return true;
    } catch {
      return false;
    }
  }

  static async fillDraft({ brief, projectName } = {}) {
    const proposal = await WorkGraphPage.proposePlan({ brief, projectName });
    if (proposal.ok === false) return proposal;
    const draft = { ...proposal, saved_at: new Date().toISOString() };
    try {
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch {
      return { ok: false, reason: "This browser cannot keep a local draft." };
    }
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("workgraph:draft", { detail: draft }));
    }
    return {
      ok: true,
      saved: true,
      storage: "sessionStorage",
      draft,
      note:
        "Draft saved in this tab only. The graph did not change. " +
        "Review it and confirm before accepting; cancel changes nothing.",
    };
  }
}
