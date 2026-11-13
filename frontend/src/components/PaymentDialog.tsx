import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getPaymentPreview, money, recordPayment, statusLabel } from "../api";
import type { PaymentPreview, PaymentResult } from "../types";

type Props = {
  invoiceId: string;
  onClose: () => void;
  onPaid: (result: PaymentResult) => void;
};

export function PaymentDialog({ invoiceId, onClose, onPaid }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [preview, setPreview] = useState<PaymentPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const submittingRef = useRef(false);

  useEffect(() => {
    let live = true;
    setPreview(null);
    setError(null);
    getPaymentPreview(invoiceId)
      .then((data) => live && setPreview(data))
      .catch((reason: unknown) => {
        if (!live) return;
        setError(reason instanceof ApiError ? reason.message : "The payment preview could not be loaded.");
      });
    return () => {
      live = false;
    };
  }, [invoiceId, attempt]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    const handleCancel = (event: Event) => {
      event.preventDefault();
      if (!submittingRef.current) onCloseRef.current();
    };
    dialog.addEventListener("cancel", handleCancel);
    document.body.classList.add("modal-open");
    return () => {
      dialog.removeEventListener("cancel", handleCancel);
      document.body.classList.remove("modal-open");
    };
  }, []);

  const close = useCallback(() => {
    if (submittingRef.current) return;
    onCloseRef.current();
  }, []);

  async function confirm() {
    if (!preview || submittingRef.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      const result = await recordPayment(preview.invoice.id, preview.amount_cents);
      onPaid(result);
    } catch (reason) {
      submittingRef.current = false;
      setError(reason instanceof ApiError ? reason.message : "The payment could not be recorded.");
      setSubmitting(false);
    }
  }

  return (
    <dialog
      ref={ref}
      className="payment-dialog"
      aria-labelledby="payment-title"
      onClick={(event) => {
        if (event.target === ref.current) close();
      }}
    >
      <div className="dialog-inner">
        <header className="dialog-head">
          <div>
            <p className="eyebrow">Sample payment · irreversible</p>
            <h2 id="payment-title">
              {preview ? `Record ${money(preview.amount_cents)}?` : "Record sample payment"}
            </h2>
          </div>
          <button
            className="icon-button"
            type="button"
            onClick={close}
            disabled={submitting}
            aria-label="Close payment dialog"
          >
            ×
          </button>
        </header>

        {!preview && !error && (
          <div className="dialog-loading" aria-busy="true" aria-live="polite">
            <span className="skeleton skeleton-line title" />
            <span className="skeleton skeleton-line" />
            <span className="skeleton skeleton-block" />
            <p>Reading the invoice and its deliverable…</p>
          </div>
        )}

        {error && !preview && (
          <div className="dialog-error" role="alert">
            <p className="empty-kicker">Preview unavailable</p>
            <p>{error}</p>
            <button className="btn btn-secondary" type="button" onClick={() => setAttempt((value) => value + 1)}>
              Try again
            </button>
          </div>
        )}

        {preview && (
          <>
            <div className="pay-summary">
              <div className="pay-amount">
                <span className="pay-amount-label">Amount</span>
                <strong>{money(preview.amount_cents)}</strong>
                <span className="pay-cents">{preview.amount_cents.toLocaleString("en-US")} integer cents</span>
              </div>
              <dl className="pay-facts">
                <div>
                  <dt>Project</dt>
                  <dd>{preview.project.name}</dd>
                </div>
                <div>
                  <dt>Milestone</dt>
                  <dd>{preview.milestone.name}</dd>
                </div>
                <div>
                  <dt>Invoice</dt>
                  <dd>
                    <code>{preview.invoice.number}</code> · {statusLabel(preview.invoice.status)}
                  </dd>
                </div>
                <div>
                  <dt>Unlocks</dt>
                  <dd>{preview.deliverables.map((deliverable) => deliverable.name).join(", ")}</dd>
                </div>
              </dl>
            </div>

            <section className="pay-changes" aria-labelledby="changes-title">
              <h3 id="changes-title">What will change in the graph</h3>
              <ol>
                {preview.status_changes.map((change) => (
                  <li key={change.entity}>
                    <span>{change.entity}</span>
                    <span className="change-value">
                      {change.from} <span aria-hidden="true">→</span> {change.to}
                    </span>
                  </li>
                ))}
                <li>
                  <span>Create one Payment node</span>
                  <span className="change-value">sample · {preview.amount_cents.toLocaleString("en-US")} cents</span>
                </li>
                {preview.edges_to_create.map((edge) => (
                  <li key={edge}>
                    <span>Create edge</span>
                    <code className="change-edge">{edge}</code>
                  </li>
                ))}
              </ol>
              <p className="pay-note">{preview.note}</p>
            </section>

            {error && (
              <p className="alert alert-error" role="alert">
                {error}
              </p>
            )}

            <footer className="dialog-actions">
              <button className="btn btn-secondary" type="button" onClick={close} disabled={submitting}>
                Cancel · change nothing
              </button>
              <button className="btn btn-primary" type="button" onClick={confirm} disabled={submitting}>
                {submitting ? "Recording…" : "Confirm sample payment"}
              </button>
            </footer>
            <p className="dialog-fineprint">
              Writes to the local graph only. No card, no PayPal, no real money.
            </p>
          </>
        )}
      </div>
    </dialog>
  );
}
