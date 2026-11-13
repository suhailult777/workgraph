// Shared browser-side operations for the WorkGraph assistant.
// Reads use the same public API as the React page. The draft is kept in
// sessionStorage only and never written to the graph.

const STATE_URL = "/api/graph/state";
const SIMILAR_URL = "/api/graph/similar";
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
    return { ok: false, reason };
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
        "Accepting a plan is not available in this milestone.",
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
        "Accepting a plan is not available in this milestone.",
    };
  }
}
