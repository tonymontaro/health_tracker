import { useEffect, useId, useRef } from "react";

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  pending = false,
  error = null,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  pending?: boolean;
  error?: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const current = dialog.current;
    if (!current) return;
    if (open && !current.open) current.showModal();
    if (!open && current.open) current.close();
  }, [open]);
  return <dialog
    className="confirm-dialog"
    ref={dialog}
    aria-labelledby={titleId}
    onCancel={(event) => {
      if (pending) event.preventDefault();
      else onCancel();
    }}
    onClose={onCancel}
  >
    <p className="eyebrow">Confirm action</p>
    <h2 id={titleId}>{title}</h2>
    <p>{description}</p>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="actions">
      <button className="quiet" type="button" disabled={pending} onClick={onCancel}>Cancel</button>
      <button className="primary destructive" type="button" disabled={pending} onClick={onConfirm}>{pending ? "Working..." : confirmLabel}</button>
    </div>
  </dialog>;
}
