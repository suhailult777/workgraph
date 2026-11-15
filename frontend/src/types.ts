export type Status = "DONE" | "PAID" | "SENT" | "BLOCKED" | "READY" | "DRAFT" | string;

export type Invoice = {
  id: string;
  number: string;
  status: Status;
  amount_cents: number;
};

export type Payment = {
  id: string;
  invoice_id: string;
  invoice: string;
  amount_cents: number;
  method: string;
  external_id: string | null;
  recorded_at: string | null;
};

export type Deliverable = {
  id: string;
  name: string;
  unlocked: boolean;
  payment_id: string | null;
};

export type Blocker = {
  path: string[];
  reason: "unpaid_invoice" | "not_done" | string;
  invoice: string | null;
  amount_cents: number | null;
};

export type Milestone = {
  id: string;
  name: string;
  status: Status;
  amount_cents: number;
  invoice: Invoice | null;
  deliverables: Deliverable[];
  parents: { id: string; name: string }[];
  blocked_by: Blocker[];
  blocked: boolean;
  can_complete: boolean;
  complete_block_reason: string | null;
  can_pay: boolean;
  pay_block_reason: string | null;
  unlocked: boolean;
};

export type GraphNode = {
  id: string;
  kind: "Party" | "Project" | "Milestone" | "Invoice" | "Payment" | "Deliverable" | string;
  label: string;
  status: Status | null;
  amount_cents: number | null;
  meta: string;
};

export type GraphEdge = {
  from: string;
  to: string;
  type: string;
};

export type ProjectDetail = {
  project: {
    id: string;
    name: string;
    status: string;
    client: string | null;
    owner: string | null;
    skills: string[];
  };
  stats: {
    milestones: number;
    done: number;
    blocked: number;
    paid_cents: number;
    total_cents: number;
    unlocked_deliverables: number;
  };
  milestones: Milestone[];
  dependencies: { source: string; target: string }[];
  invoices: Invoice[];
  payments: Payment[];
  next: { id: string; name: string; status: Status; amount_cents: number } | null;
  graph: { nodes: GraphNode[]; edges: GraphEdge[] };
};

export type ProjectSummary = {
  id: string;
  name: string;
  status: string;
  client: string | null;
  owner: string | null;
  milestones: number;
  done: number;
  blocked: number;
  paid_cents: number;
  total_cents: number;
  next: { id: string; name: string; status: Status; amount_cents: number } | null;
  milestone_states: { id: string; name: string; status: Status }[];
};

export type PaymentPreview = {
  invoice: Invoice;
  milestone: { id: string; name: string; status: Status };
  project: { id: string; name: string };
  amount_cents: number;
  deliverables: { id: string; name: string }[];
  status_changes: { entity: string; from: Status; to: Status }[];
  edges_to_create: string[];
  note: string;
};

export type PaymentResult = {
  payment_id: string;
  invoice_id: string;
  milestone_id: string;
  amount_cents: number;
  unlocked: { id: string; name: string }[];
  project: ProjectDetail;
};

export type Health = {
  status: string;
  service: string;
  store: string;
  graph_ready: boolean;
  assistant_live: boolean;
  paypal_sandbox_configured: boolean;
  paypal_webhook_configured: boolean;
  storage_kind: string;
};

export type AppConfig = {
  assistant_live: boolean;
  assistant_mock: boolean;
  paypal_sandbox_configured: boolean;
  paypal_webhook_configured: boolean;
  storage_kind: string;
  environment: "production" | "development" | string;
};

export type DeclinePath = {
  invoice: Invoice;
  milestone: { id: string; name: string };
  project: { id: string; name: string };
  blocked: {
    blocked_id: string;
    blocked: string;
    status: Status;
    reason: string;
  }[];
  blocked_count: number;
};

export type SimilarWork = {
  skill: string;
  work: {
    party: string;
    project: string;
    milestone: string;
    invoice: string;
    amount_cents: number;
  }[];
};

export type PayPalOrderResult = {
  order: {
    id: string;
    invoice_id: string;
    amount_cents: number;
    currency: string;
    status: string;
    approve_url: string;
    mock?: boolean;
  };
  approve_url: string;
  invoice: Invoice;
  amount_cents: number;
};

export type PayPalCaptureResult = {
  already_captured: boolean;
  order: PayPalOrderResult["order"];
  capture_id?: string;
  payment?: PaymentResult;
  invoice?: Invoice;
  payment_id?: string;
};
