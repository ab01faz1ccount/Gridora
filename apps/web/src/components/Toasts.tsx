import { useEffect } from "react";
import { useT } from "@/i18n";
import { useUi, type Toast } from "@/state/ui";

function ToastItem({ toast }: { toast: Toast }) {
  const dismiss = useUi((s) => s.dismissToast);
  const t = useT();
  useEffect(() => {
    const timer = setTimeout(() => dismiss(toast.id), 8000);
    return () => clearTimeout(timer);
  }, [toast.id, dismiss]);
  return (
    <div className={`toast toast-${toast.kind}`} role={toast.kind === "error" ? "alert" : "status"}>
      <span>{toast.text}</span>
      <button type="button" className="toast-close" onClick={() => dismiss(toast.id)}
        aria-label={t("common.dismiss")}>
        ×
      </button>
    </div>
  );
}

export function Toasts() {
  const toasts = useUi((s) => s.toasts);
  return (
    <div className="toasts">
      {toasts.map((x) => (
        <ToastItem key={x.id} toast={x} />
      ))}
    </div>
  );
}
