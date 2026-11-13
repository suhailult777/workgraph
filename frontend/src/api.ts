import type {
  AppConfig,
  DeclinePath,
  Health,
  PaymentPreview,
  PaymentResult,
  PayPalCaptureResult,
  PayPalOrderResult,
  ProjectDetail,
  ProjectSummary,
  SimilarWork,
} from "./types";

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code = "request_failed", status = 0) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
      ...init,
    });
  } catch {
    throw new ApiError("Could not reach the local graph service.", "network", 0);
  }

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    let message: string;
    let code = "request_failed";
    if (Array.isArray(detail)) {
      const first = detail[0];
      const location = Array.isArray(first?.loc) ? first.loc.filter((part: unknown) => part !== "body").join(".") : "";
      message = first?.msg
        ? `${first.msg}${location ? ` (${location})` : ""}`
        : `Request failed with status ${response.status}.`;
      code = first?.type ?? "validation_error";
    } else if (typeof detail === "string") {
      message = detail;
    } else {
      message = detail?.message ?? `Request failed with status ${response.status}.`;
      code = detail?.code ?? "request_failed";
    }
    throw new ApiError(message, code, response.status);
  }
  return body as T;
}

export function getHealth(): Promise<Health> {
  return request<Health>("/api/health");
}

export function getConfig(): Promise<AppConfig> {
  return request<AppConfig>("/api/config");
}

export function getProjects(): Promise<{ projects: ProjectSummary[] }> {
  return request<{ projects: ProjectSummary[] }>("/api/projects");
}

export function getProject(id: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/api/projects/${encodeURIComponent(id)}`);
}

export function createSampleProject(name: string): Promise<ProjectDetail> {
  return request<ProjectDetail>("/api/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function acceptPlan(
  projectName: string,
  milestones: { name: string; depends_on: string[] }[],
): Promise<{ accepted: boolean; project: ProjectDetail }> {
  return request("/api/plans/accept", {
    method: "POST",
    body: JSON.stringify({ project_name: projectName, milestones }),
  });
}

export function getDeclinePath(invoice: string): Promise<DeclinePath> {
  return request<DeclinePath>(`/api/graph/decline-path?invoice=${encodeURIComponent(invoice)}`);
}

export function searchSimilarWork(skill: string): Promise<SimilarWork> {
  return request<SimilarWork>(`/api/graph/similar?skill=${encodeURIComponent(skill)}`);
}

export function createPayPalOrder(invoiceId: string): Promise<PayPalOrderResult> {
  return request<PayPalOrderResult>("/api/paypal/orders", {
    method: "POST",
    body: JSON.stringify({ invoice_id: invoiceId }),
  });
}

export function capturePayPalOrder(orderId: string): Promise<PayPalCaptureResult> {
  return request<PayPalCaptureResult>(`/api/paypal/orders/${encodeURIComponent(orderId)}/capture`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function getPaymentPreview(invoiceId: string): Promise<PaymentPreview> {
  return request<PaymentPreview>(
    `/api/invoices/${encodeURIComponent(invoiceId)}/payment-preview`,
  );
}

export function recordPayment(invoiceId: string, amountCents: number): Promise<PaymentResult> {
  return request<PaymentResult>("/api/payments", {
    method: "POST",
    body: JSON.stringify({ invoice_id: invoiceId, amount_cents: amountCents }),
  });
}

export function completeMilestone(milestoneId: string): Promise<ProjectDetail & {
  milestone: { id: string; name: string; status: string };
}> {
  return request(`/api/milestones/${encodeURIComponent(milestoneId)}/complete`, {
    method: "POST",
  });
}

export function money(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

export function compactMoney(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(cents / 100);
}

export function statusLabel(status: string): string {
  switch (status) {
    case "DONE":
      return "Done";
    case "PAID":
      return "Paid";
    case "SENT":
      return "Awaiting payment";
    case "BLOCKED":
      return "Blocked";
    case "READY":
      return "Ready";
    case "UNLOCKED":
      return "Unlocked";
    case "LOCKED":
      return "Locked";
    default:
      return status.charAt(0) + status.slice(1).toLowerCase();
  }
}
