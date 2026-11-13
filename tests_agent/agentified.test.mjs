import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { ActionRegistry } from "../public/runtime/actions.js";
import { AgentNetwork, validateNetwork } from "../public/runtime/kernel.js";
import { buildToolTable, runAgent } from "../public/runtime/runner.js";
import { TraceBus } from "../public/runtime/trace.js";
import { registerActions } from "../public/site-actions.js";
import { WorkGraphPage } from "../public/page-bridge.js";
import { ScriptedModel } from "./scripted-model.mjs";

const NETWORK_NAME = "workgraph";
const BASE = "http://127.0.0.1:8090";
const ACTION_NAMES = [
  "get_graph_state",
  "search_similar_work",
  "get_decline_path",
  "propose_plan",
  "fill_draft",
  "accept_plan",
  "record_payment",
];

const STATE = {
  ok: true,
  mode: "sample",
  note: "Sample data only.",
  projects: [
    {
      id: "proj-harbour",
      name: "Harbour rebrand",
      status: "active",
      client: "Northwind Studio",
      owner: "Mira Chen",
      stats: { milestones: 4, done: 1, blocked: 2, paid_cents: 180000, total_cents: 830000 },
      milestones: [
        {
          id: "ms-h1",
          name: "Discovery",
          status: "DONE",
          amount_cents: 180000,
          invoice: { id: "inv-h1", number: "WG-1001", status: "PAID", amount_cents: 180000 },
          parents: [],
          blocked_by: [],
          can_complete: false,
          can_pay: false,
          deliverables: [{ name: "Discovery notes", unlocked: true }],
        },
        {
          id: "ms-h2",
          name: "Design system",
          status: "SENT",
          amount_cents: 240000,
          invoice: { id: "inv-h2", number: "WG-1002", status: "SENT", amount_cents: 240000 },
          parents: ["Discovery"],
          blocked_by: [],
          can_complete: false,
          can_pay: true,
          deliverables: [{ name: "Design system kit", unlocked: false }],
        },
        {
          id: "ms-h3",
          name: "Build",
          status: "BLOCKED",
          amount_cents: 320000,
          invoice: null,
          parents: ["Design system"],
          blocked_by: [
            {
              path: ["Build", "Design system"],
              reason: "unpaid_invoice",
              invoice: "WG-1002",
              amount_cents: 240000,
            },
          ],
          can_complete: false,
          can_pay: false,
          deliverables: [{ name: "Build preview", unlocked: false }],
        },
      ],
      invoices: [
        { id: "inv-h1", number: "WG-1001", status: "PAID", amount_cents: 180000 },
        { id: "inv-h2", number: "WG-1002", status: "SENT", amount_cents: 240000 },
      ],
      payments: [
        { id: "pay-h1", invoice: "WG-1001", amount_cents: 180000, method: "sample" },
      ],
    },
    {
      id: "proj-atlas",
      name: "Atlas dashboard",
      status: "paid",
      client: "Kestrel Labs",
      owner: "Jules Okafor",
      stats: { milestones: 2, done: 2, blocked: 0, paid_cents: 380000, total_cents: 380000 },
      milestones: [],
      invoices: [],
      payments: [],
    },
  ],
  skills: ["Design systems", "Front-end build", "User research"],
  node_counts: [{ label: "Project", count: 2 }],
};

const SIMILAR = {
  skill: "Design systems",
  work: [
    {
      party: "Jules Okafor",
      project: "Atlas dashboard",
      milestone: "Audit",
      invoice: "WG-1003",
      amount_cents: 120000,
    },
    {
      party: "Mira Chen",
      project: "Harbour rebrand",
      milestone: "Discovery",
      invoice: "WG-1001",
      amount_cents: 180000,
    },
  ],
};

const DECLINE = {
  invoice: { id: "inv-h2", number: "WG-1002", status: "SENT", amount_cents: 240000 },
  milestone: { id: "ms-h2", name: "Design system" },
  project: { id: "proj-harbour", name: "Harbour rebrand" },
  blocked: [
    {
      blocked_id: "ms-h3",
      blocked: "Build",
      status: "BLOCKED",
      reason: "unpaid_invoice",
    },
  ],
  blocked_count: 1,
};

const ACCEPTED = {
  ok: true,
  accepted: true,
  plan: [
    { name: "Scope", depends_on: [] },
    { name: "Design", depends_on: ["Scope"] },
    { name: "Build", depends_on: ["Design"] },
    { name: "Handover", depends_on: ["Build"] },
  ],
  project: STATE.projects[0],
  node_ids: {
    project: "proj-new",
    milestones: ["ms-new-1", "ms-new-2", "ms-new-3", "ms-new-4"],
    invoices: ["inv-new-1", "inv-new-2"],
  },
};

const PAID = {
  ok: true,
  payment_id: "pay-test",
  invoice_id: "inv-h2",
  milestone_id: "ms-h2",
  amount_cents: 240000,
  unlocked: [{ id: "del-h2", name: "Design system kit" }],
  project: STATE.projects[0],
};

const storage = new Map();
Object.defineProperty(globalThis, "sessionStorage", {
  configurable: true,
  value: {
    getItem: (key) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
    clear: () => storage.clear(),
  },
});

const fetchCalls = [];
globalThis.fetch = async (url, options = {}) => {
  const target = String(url);
  fetchCalls.push({
    url: target,
    method: options.method || "GET",
    body: options.body ? JSON.parse(options.body) : null,
  });
  if (target === "/api/graph/state") {
    return new Response(JSON.stringify(STATE), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }
  if (target.startsWith("/api/graph/similar?skill=")) {
    return new Response(JSON.stringify(SIMILAR), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }
  if (target.startsWith("/api/graph/decline-path?invoice=")) {
    return new Response(JSON.stringify(DECLINE), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }
  if (target === "/api/plans/accept") {
    return new Response(JSON.stringify(ACCEPTED), {
      status: 201,
      headers: { "content-type": "application/json" },
    });
  }
  if (target === "/api/payments") {
    return new Response(JSON.stringify(PAID), {
      status: 201,
      headers: { "content-type": "application/json" },
    });
  }
  return new Response(JSON.stringify({ detail: "No fixture for this request." }), {
    status: 404,
    headers: { "content-type": "application/json" },
  });
};

async function load() {
  const config = JSON.parse(
    await readFile(new URL("../public/workgraph.network.json", import.meta.url), "utf8"),
  );
  const manifest = JSON.parse(
    await readFile(new URL("../public/agent-manifest.json", import.meta.url), "utf8"),
  );
  return { config, manifest, network: new AgentNetwork(config, NETWORK_NAME) };
}

function scope() {
  return { base: BASE, network: NETWORK_NAME };
}

function registry() {
  const instance = new ActionRegistry();
  registerActions({
    register: instance.register.bind(instance, scope()),
  });
  return instance;
}

function ref(instance, name) {
  for (const entry of instance.catalog(scope())) {
    if (entry.name === name) return entry.ref;
  }
  throw new Error(`Action ${name} is not registered.`);
}

async function runAction(instance, name, args = {}) {
  return runActionWithConfirm(instance, name, args, async () => true);
}

async function runActionWithConfirm(instance, name, args, confirm) {
  const plan = instance.prepare({
    kind: "action",
    action: ref(instance, name),
    arguments: args,
  });
  const receipts = await instance.execute(plan, confirm, "node-test");
  return receipts ? receipts[0] : null;
}

function context(loaded, actions, model, confirm = async () => true) {
  return {
    network: loaded.network,
    manifest: loaded.manifest,
    actions,
    baseOrigin: BASE,
    displayOrigin: "127.0.0.1:8090",
    trace: new TraceBus(),
    isTop: true,
    frontMan: loaded.network.findFrontMan(),
    history: [],
    llm: model,
    confirmWebsiteActions: confirm,
  };
}

test("the published network and manifest are valid and name three agents", async () => {
  const loaded = await load();
  assert.deepEqual(validateNetwork(loaded.network).errors, []);
  assert.equal(loaded.network.findFrontMan(), "workgraph_coordinator");
  const names = loaded.network.config.tools.map((tool) => tool.name);
  assert.deepEqual(names.sort(), ["ledger_specialist", "plan_specialist", "workgraph_coordinator"]);
  assert.deepEqual(loaded.manifest.actions.agentTools, ACTION_NAMES);
  assert.equal(loaded.manifest.llm_router.mock, false);
  assert.equal(loaded.manifest.llm_router.base_url, "/api/assistant");
  assert.ok(loaded.manifest.llm_router.byok_router.startsWith("https://"));
});

test("reads, a local draft, and two irreversible confirmed writes are registered", () => {
  const actions = registry();
  const entries = actions.catalog(scope());
  assert.deepEqual(entries.map((entry) => entry.name).sort(), [...ACTION_NAMES].sort());
  for (const entry of entries) {
    assert.equal(entry.availability, "local-only");
  }
  assert.equal(entries.find((entry) => entry.name === "fill_draft").effect, "write");
  assert.equal(entries.find((entry) => entry.name === "accept_plan").effect, "irreversible");
  assert.equal(entries.find((entry) => entry.name === "record_payment").effect, "irreversible");
  assert.equal(entries.find((entry) => entry.name === "get_decline_path").effect, "read");
});

test("get_graph_state returns exact blocked paths and invoices", async () => {
  const receipt = await runAction(registry(), "get_graph_state");
  assert.equal(receipt.status, "succeeded");
  assert.equal(receipt.result.ok, true);
  const harbour = receipt.result.projects.find((project) => project.name === "Harbour rebrand");
  const build = harbour.milestones.find((milestone) => milestone.name === "Build");
  assert.deepEqual(build.blocked_by, [
    {
      path: ["Build", "Design system"],
      reason: "unpaid_invoice",
      invoice: "WG-1002",
      amount_cents: 240000,
    },
  ]);
  assert.equal(receipt.result.skills.includes("Design systems"), true);
  assert.equal("graph" in harbour, false);
});

test("search_similar_work uses the graph traversal and encodes the skill", async () => {
  fetchCalls.length = 0;
  const receipt = await runAction(registry(), "search_similar_work", {
    skill: "Design systems",
  });
  assert.equal(receipt.status, "succeeded");
  assert.equal(receipt.result.work.length, 2);
  assert.equal(receipt.result.work[0].party, "Jules Okafor");
  assert.ok(
    fetchCalls.some((call) => call.url === "/api/graph/similar?skill=Design%20systems"),
  );
});

test("get_decline_path returns every milestone waiting on the invoice", async () => {
  fetchCalls.length = 0;
  const receipt = await runAction(registry(), "get_decline_path", { invoice: "WG-1002" });
  assert.equal(receipt.status, "succeeded");
  assert.equal(receipt.result.invoice.number, "WG-1002");
  assert.equal(receipt.result.blocked[0].blocked_id, "ms-h3");
  assert.equal(receipt.result.blocked_count, 1);
  assert.ok(
    fetchCalls.some((call) => call.url === "/api/graph/decline-path?invoice=WG-1002"),
  );
});

test("propose_plan returns a draft with dependencies and no invented amounts", async () => {
  fetchCalls.length = 0;
  const receipt = await runAction(registry(), "propose_plan", {
    brief: "A new brand and design system project.",
    projectName: "Brand refresh",
  });
  assert.equal(receipt.status, "succeeded");
  const draft = receipt.result;
  assert.equal(draft.draft, true);
  assert.equal(draft.projectName, "Brand refresh");
  assert.deepEqual(
    draft.milestones.map((milestone) => milestone.name),
    ["Scope", "Design", "Build", "Handover"],
  );
  assert.deepEqual(draft.milestones[1].depends_on, ["Scope"]);
  assert.equal(draft.milestones.some((milestone) => "amount_cents" in milestone), false);
  assert.equal(draft.similar_work[0].invoice, "WG-1003");
  assert.ok(fetchCalls.every((call) => call.method === "GET"));
});

test("fill_draft saves only a sessionStorage draft and never posts to the graph", async () => {
  storage.clear();
  fetchCalls.length = 0;
  const receipt = await runAction(registry(), "fill_draft", {
    brief: "A new research and design project.",
    projectName: "Draft example",
  });
  assert.equal(receipt.status, "succeeded");
  assert.equal(receipt.result.saved, true);
  assert.equal(receipt.result.storage, "sessionStorage");
  assert.equal(WorkGraphPage.readDraft().projectName, "Draft example");
  assert.ok(fetchCalls.every((call) => call.method === "GET"));
  assert.equal(fetchCalls.some((call) => call.url === "/api/payments"), false);
});

test("fill_draft refuses an empty brief without changing storage", async () => {
  storage.clear();
  const receipt = await runAction(registry(), "fill_draft", { brief: "   " });
  assert.equal(receipt.status, "succeeded");
  assert.equal(receipt.result.ok, false);
  assert.equal(receipt.result.field, "brief");
  assert.equal(WorkGraphPage.readDraft(), null);
});

test("accept_plan cancels without a POST or graph change", async () => {
  fetchCalls.length = 0;
  const receipt = await runActionWithConfirm(
    registry(),
    "accept_plan",
    {
      projectName: "Brand refresh",
      milestones: ACCEPTED.plan,
    },
    async () => false,
  );
  assert.equal(receipt, null);
  assert.equal(fetchCalls.some((call) => call.method === "POST"), false);
});

test("accept_plan posts the reviewed plan after confirmation", async () => {
  fetchCalls.length = 0;
  const receipt = await runAction(registry(), "accept_plan", {
    projectName: "Brand refresh",
    milestones: ACCEPTED.plan,
  });
  assert.equal(receipt.status, "succeeded");
  assert.equal(receipt.result.accepted, true);
  const post = fetchCalls.find((call) => call.url === "/api/plans/accept");
  assert.equal(post.method, "POST");
  assert.equal(post.body.project_name, "Brand refresh");
  assert.deepEqual(
    post.body.milestones.map((step) => step.name),
    ["Scope", "Design", "Build", "Handover"],
  );
});

test("record_payment cancels without a POST or graph change", async () => {
  fetchCalls.length = 0;
  const receipt = await runActionWithConfirm(
    registry(),
    "record_payment",
    { invoiceId: "inv-h2", amountCents: 240000 },
    async () => false,
  );
  assert.equal(receipt, null);
  assert.equal(fetchCalls.some((call) => call.url === "/api/payments"), false);
});

test("record_payment posts the exact amount after confirmation", async () => {
  fetchCalls.length = 0;
  const receipt = await runAction(registry(), "record_payment", {
    invoiceId: "inv-h2",
    amountCents: 240000,
  });
  assert.equal(receipt.status, "succeeded");
  assert.equal(receipt.result.payment_id, "pay-test");
  const post = fetchCalls.find((call) => call.url === "/api/payments");
  assert.deepEqual(post.body, { invoice_id: "inv-h2", amount_cents: 240000 });
});

test("record_payment refuses a non-integer amount before any POST", async () => {
  fetchCalls.length = 0;
  const instance = registry();
  assert.throws(
    () =>
      instance.prepare({
        kind: "action",
        action: ref(instance, "record_payment"),
        arguments: { invoiceId: "inv-h2", amountCents: 2400.5 },
      }),
    /Invalid arguments.amountCents/,
  );
  assert.equal(fetchCalls.some((call) => call.url === "/api/payments"), false);
});


test("a scripted model can read the graph and answer from the tool result", async () => {
  const loaded = await load();
  const actions = registry();
  const model = new ScriptedModel([
    { tool: "website_get_graph_state", arguments: {} },
    { text: "Build [ms-h3] waits on WG-1002 for 240000 cents." },
  ]);
  const ctx = context(loaded, actions, model);
  const result = await runAgent(
    ctx,
    ctx.frontMan,
    "Which milestones are blocked by an unpaid invoice?",
    null,
    [],
  );
  assert.ok(model.toolNames(0).includes("website_get_graph_state"));
  assert.equal(model.toolResults(1)[0].status, "succeeded");
  assert.equal(model.toolResults(1)[0].result.projects[0].name, "Harbour rebrand");
  assert.match(result.text, /WG-1002/);
  assert.match(result.text, /ms-h3/);
});

test("a scripted model accepts a plan only after the confirmation callback", async () => {
  const loaded = await load();
  const actions = registry();
  const model = new ScriptedModel([
    {
      tool: "website_accept_plan",
      arguments: { projectName: "Brand refresh", milestones: ACCEPTED.plan },
    },
    { text: "Accepted the plan for proj-new." },
  ]);
  const ctx = context(loaded, actions, model, async () => true);
  const result = await runAgent(
    ctx,
    ctx.frontMan,
    "Accept the plan for a new brand project.",
    null,
    [],
  );
  assert.equal(model.toolResults(1)[0].status, "succeeded");
  assert.equal(model.toolResults(1)[0].result.accepted, true);
  assert.match(result.text, /proj-new/);
});

test("a cancelled plan confirmation leaves the graph unchanged", async () => {
  const loaded = await load();
  const actions = registry();
  const model = new ScriptedModel([
    {
      tool: "website_accept_plan",
      arguments: { projectName: "Brand refresh", milestones: ACCEPTED.plan },
    },
    { text: "The plan was not accepted." },
  ]);
  const ctx = context(loaded, actions, model, async () => false);
  const result = await runAgent(
    ctx,
    ctx.frontMan,
    "Accept the plan for a new brand project.",
    null,
    [],
  );
  assert.equal(model.toolResults(1)[0].status, "cancelled");
  assert.equal(model.toolResults(1)[0].result, undefined);
  assert.match(result.text, /not accepted/);
});

test("a scripted model records a sample payment only after confirmation", async () => {
  const loaded = await load();
  const actions = registry();
  const model = new ScriptedModel([
    {
      tool: "website_record_payment",
      arguments: { invoiceId: "inv-h2", amountCents: 240000 },
    },
    { text: "Recorded pay-test for inv-h2." },
  ]);
  const ctx = context(loaded, actions, model, async () => true);
  const result = await runAgent(
    ctx,
    ctx.frontMan,
    "Record the sample payment for WG-1002.",
    null,
    [],
  );
  assert.equal(model.toolResults(1)[0].status, "succeeded");
  assert.equal(model.toolResults(1)[0].result.payment_id, "pay-test");
  assert.match(result.text, /pay-test/);
});

test("a card-charge request is answered without a tool call and no card-charge tool exists", async () => {
  const loaded = await load();
  const actions = registry();
  const model = new ScriptedModel([
    { text: "I can't charge a card or take real money here. This site records sample payments only." },
  ]);
  const ctx = context(loaded, actions, model);
  const spec = loaded.network.getAgentSpec(loaded.network.findFrontMan());
  const table = await buildToolTable(ctx, spec, [], null);
  assert.equal(table.toolByName.has("website_record_sample_payment"), false);
  assert.equal(table.toolByName.has("website_record_payment"), true);
  assert.equal(table.toolByName.has("website_accept_plan"), true);
  assert.equal(table.toolByName.has("website_get_decline_path"), true);
  assert.equal(table.toolByName.has("website_fill_draft"), true);
  const result = await runAgent(
    ctx,
    ctx.frontMan,
    "Record a real card payment for the design system.",
    null,
    [],
  );
  assert.ok(model.toolNames(0).includes("website_get_graph_state"));
  assert.match(result.text, /can't charge a card/);
});
