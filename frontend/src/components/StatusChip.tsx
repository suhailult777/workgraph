import { statusLabel } from "../api";

export function StatusChip({ status, quiet = false }: { status: string; quiet?: boolean }) {
  return (
    <span className={`status-chip status-${status.toLowerCase()}${quiet ? " is-quiet" : ""}`}>
      <span className="status-dot" aria-hidden="true" />
      {statusLabel(status)}
    </span>
  );
}
