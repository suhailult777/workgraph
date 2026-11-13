import { statusLabel, money } from "../api";
import type { GraphEdge, GraphNode } from "../types";

const NODE_W = 150;
const NODE_H = 62;
const X: Record<string, number> = {
  Party: 24,
  Project: 24,
  Milestone: 368,
  Invoice: 572,
  Payment: 740,
  Deliverable: 908,
};
const CANVAS_W = 1080;

type Placed = { node: GraphNode; x: number; y: number };

function accentFor(node: GraphNode): string {
  if (node.kind === "Party") return "var(--line-strong)";
  if (node.kind === "Project") return "var(--green)";
  if (node.kind === "Deliverable") return node.status === "UNLOCKED" ? "var(--green)" : "var(--line-strong)";
  switch (node.status) {
    case "DONE":
    case "PAID":
      return "var(--green)";
    case "SENT":
      return "var(--amber)";
    case "BLOCKED":
      return "var(--red)";
    case "READY":
      return "var(--blue)";
    default:
      return "var(--line-strong)";
  }
}

function shorten(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function nodeMeta(node: GraphNode): string {
  switch (node.kind) {
    case "Project":
      return shorten(node.meta.split(" · ")[0], 28);
    case "Milestone":
      return node.status ?? "";
    case "Invoice":
      return `Invoice · ${node.status ?? ""}`;
    case "Payment":
      return "Sample · paid";
    case "Deliverable":
      return statusLabel(node.status ?? "");
    default:
      return node.meta;
  }
}

export function GraphView({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const milestones = nodes.filter((node) => node.kind === "Milestone");
  const positioned = new Map<string, Placed>();
  const placed: Placed[] = [];

  const deliverablesByMilestone = new Map<string, GraphNode[]>();
  const invoiceByMilestone = new Map<string, GraphNode>();
  const paymentByInvoice = new Map<string, GraphNode>();
  for (const edge of edges) {
    const from = byId.get(edge.from);
    const to = byId.get(edge.to);
    if (!from || !to) continue;
    if (edge.type === "PRODUCES") {
      const list = deliverablesByMilestone.get(from.id) ?? [];
      list.push(to);
      deliverablesByMilestone.set(from.id, list);
    }
    if (edge.type === "INVOICED") invoiceByMilestone.set(from.id, to);
    if (edge.type === "PAID_BY") paymentByInvoice.set(from.id, to);
  }

  const parties = nodes.filter((node) => node.kind === "Party");
  const extraPartyRows = Math.max(0, parties.length - 2);

  let rowY = 92 + extraPartyRows * 82;
  for (const milestone of milestones) {
    const deliverables = deliverablesByMilestone.get(milestone.id) ?? [];
    const place = (node: GraphNode, x: number, y: number) => {
      const item = { node, x, y };
      positioned.set(node.id, item);
      placed.push(item);
    };
    place(milestone, X.Milestone, rowY);
    for (const deliverable of deliverables) {
      const index = deliverables.indexOf(deliverable);
      place(deliverable, X.Deliverable, rowY + index * 70);
    }
    const invoice = invoiceByMilestone.get(milestone.id);
    if (invoice) {
      place(invoice, X.Invoice, rowY);
      const payment = paymentByInvoice.get(invoice.id);
      if (payment) place(payment, X.Payment, rowY);
    }
    rowY += Math.max(94, 62 + Math.max(0, deliverables.length - 1) * 70 + 26);
  }

  const milestonePlaces = milestones
    .map((milestone) => positioned.get(milestone.id))
    .filter((p): p is Placed => Boolean(p));
  const projectCenter =
    milestonePlaces.length > 0
      ? milestonePlaces.reduce((sum, p) => sum + p.y, 0) / milestonePlaces.length
      : rowY;
  const project = nodes.find((node) => node.kind === "Project");
  if (project) {
    const item = { node: project, x: X.Project, y: Math.max(40, projectCenter) };
    positioned.set(project.id, item);
    placed.push(item);
  }
  parties.forEach((party, index) => {
    const offset =
      parties.length <= 2
        ? parties.length === 1
          ? -82
          : index === 0
            ? -82
            : 82
        : -82 - (parties.length - 1 - index) * 82;
    const item = { node: party, x: X.Party, y: Math.max(20, projectCenter + offset) };
    positioned.set(party.id, item);
    placed.push(item);
  });

  const height = Math.max(330, rowY + 28);

  function pathFor(edge: GraphEdge): string | null {
    const a = positioned.get(edge.from);
    const b = positioned.get(edge.to);
    if (!a || !b) return null;
    const ay = a.y + NODE_H / 2;
    const by = b.y + NODE_H / 2;
    if (edge.type === "DEPENDS_ON") {
      const x = a.x;
      const bulge = 32 + Math.abs(ay - by) * 0.14;
      return `M ${x} ${ay} C ${x - bulge} ${ay}, ${x - bulge} ${by}, ${x} ${by}`;
    }
    if (edge.type === "PRODUCES") {
      const x1 = a.x + NODE_W / 2;
      const x2 = b.x + NODE_W / 2;
      const y1 = a.y + NODE_H;
      const y2 = b.y + NODE_H;
      const route = Math.max(y1, y2) + 12;
      return `M ${x1} ${y1} L ${x1} ${route} Q ${x1} ${route + 7} ${x1 + 7} ${route + 7} L ${x2 - 7} ${route + 7} Q ${x2} ${route + 7} ${x2} ${route} L ${x2} ${y2}`;
    }
    if (a.x === b.x) {
      const x = a.x + NODE_W / 2;
      const y1 = a.y < b.y ? a.y + NODE_H : a.y;
      const y2 = a.y < b.y ? b.y : b.y + NODE_H;
      return `M ${x} ${y1} L ${x} ${y2}`;
    }
    const goingRight = a.x < b.x;
    const x1 = goingRight ? a.x + NODE_W : a.x;
    const x2 = goingRight ? b.x : b.x + NODE_W;
    const dx = Math.max(36, Math.abs(x2 - x1) * 0.52);
    return `M ${x1} ${ay} C ${x1 + dx} ${ay}, ${x2 - dx} ${by}, ${x2} ${by}`;
  }

  const markerFor = (type: string) => {
    if (type === "DEPENDS_ON") return "url(#arrow-red)";
    if (type === "UNLOCKS" || type === "PAID_BY") return "url(#arrow-green)";
    if (type === "INVOICED") return "url(#arrow-amber)";
    return "url(#arrow-ink)";
  };

  return (
    <div className="graph-scroll" tabIndex={0} role="region" aria-label="Project graph, scroll sideways if needed">
      <svg
        className="graph-svg"
        viewBox={`0 0 ${CANVAS_W} ${height}`}
        role="img"
        aria-labelledby="graph-svg-title graph-svg-desc"
      >
        <title id="graph-svg-title">WorkGraph project relationships</title>
        <desc id="graph-svg-desc">
          {`${nodes.length} nodes and ${edges.length} relationships. Milestones point to their invoice, payment and deliverable. Dashed edges are dependencies.`}
        </desc>
        <defs>
          <pattern id="graph-dots" width="18" height="18" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" fill="var(--line)" />
          </pattern>
          {[
            ["arrow-ink", "var(--line-strong)"],
            ["arrow-green", "var(--green)"],
            ["arrow-red", "var(--red)"],
            ["arrow-amber", "var(--amber)"],
          ].map(([id, color]) => (
            <marker
              key={id}
              id={id}
              viewBox="0 0 8 8"
              refX="6.5"
              refY="4"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 8 4 L 0 8 z" fill={color} />
            </marker>
          ))}
        </defs>
        <rect width={CANVAS_W} height={height} fill="url(#graph-dots)" opacity="0.55" />
        <g className="graph-edges">
          {edges.map((edge, index) => {
            const path = pathFor(edge);
            if (!path) return null;
            return (
              <path
                key={`${edge.type}-${edge.from}-${edge.to}-${index}`}
                d={path}
                className={`edge edge-${edge.type.toLowerCase()}`}
                markerEnd={markerFor(edge.type)}
              >
                <title>{edge.type}</title>
              </path>
            );
          })}
        </g>
        <g className="graph-nodes">
          {placed.map(({ node, x, y }) => {
            const isMilestone = node.kind === "Milestone";
            return (
              <g
                key={node.id}
                transform={`translate(${x}, ${y})`}
                className={`graph-node graph-node-${node.kind.toLowerCase()}`}
              >
                <title>
                  {`${node.kind}: ${node.label}${node.status ? ` — ${node.status}` : ""}${node.meta ? ` (${node.meta})` : ""}`}
                </title>
                <rect className="node-card" width={NODE_W} height={NODE_H} rx="6" />
                <rect width="3" height={NODE_H} rx="1.5" fill={accentFor(node)} />
                <text className="node-label" x="14" y="20">
                  {shorten(node.label, 20)}
                </text>
                <text className="node-meta" x="14" y="37">
                  {shorten(nodeMeta(node), 25)}
                </text>
                {node.amount_cents !== null && (
                  <text className="node-amount" x="14" y="53">
                    {money(node.amount_cents)}
                  </text>
                )}
                {isMilestone && node.status === "DONE" && (
                  <text className="node-mark" x={NODE_W - 12} y="20" textAnchor="end">
                    ✓
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
