import type { HistoryEntry } from "@contracts";
import { useHistory } from "@/api/hooks";
import { Button } from "@/components/Button";
import { useT } from "@/i18n";
import type { MessageKey } from "@/i18n";
import { formatNumber } from "@/i18n/format";
import { usePrefs } from "@/state/prefs";

type T = ReturnType<typeof useT>;

/**
 * Entries are labelled by the server. A label that is a catalog key ("history.cell_edit") is shown
 * in the person's language; the others (operation names) come from the server and are shown as given.
 */
export function entryLabel(e: HistoryEntry, t: T, digits: Parameters<typeof formatNumber>[1]): string {
  if (e.label === "history.cell_edit") {
    const count = Number((e.operation.params as { count?: unknown } | undefined)?.count);
    const base = t("history.cell_edit");
    return Number.isFinite(count) && count > 0
      ? `${base} (${t("history.cellsCount", { count: formatNumber(count, digits, 0) })})`
      : base;
  }
  const key = e.label as MessageKey;
  return e.label.startsWith("history.") ? (t(key) === e.label ? e.label : t(key)) : e.label;
}

export function HistoryPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const t = useT();
  const digits = usePrefs((s) => s.digits);
  const locale = usePrefs((s) => s.locale);
  const q = useHistory(id, true);
  const entries = (q.data?.pages ?? []).flat();
  const when = (iso: string) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime())
      ? iso
      : new Intl.DateTimeFormat(locale === "fa" ? "fa-IR" : "en", { dateStyle: "short", timeStyle: "short" }).format(d);
  };
  return (
    <section className="panel" aria-labelledby="history-title">
      <header className="panel-head">
        <h2 id="history-title">{t("history.title")}</h2>
        <Button onClick={onClose} aria-label={t("shell.panelClose")}>{t("shell.panelClose")}</Button>
      </header>
      {q.isPending ? <p className="muted">{t("common.loading")}</p> : null}
      {q.isError ? <p role="alert">{t("history.loadError")}</p> : null}
      {q.isSuccess && entries.length === 0 ? <p className="muted">{t("history.empty")}</p> : null}
      <ol className="history-list">
        {entries.map((e) => (
          <li key={e.id} className={e.undone ? "history-undone" : undefined}>
            <div dir="auto">{entryLabel(e, t, digits)}</div>
            <div className="muted history-meta">
              <time dateTime={e.created_at}>{when(e.created_at)}</time>
              {e.undone ? <> · {t("history.undone")}</> : null}
            </div>
          </li>
        ))}
      </ol>
      {q.hasNextPage ? (
        <Button onClick={() => void q.fetchNextPage()} disabled={q.isFetchingNextPage}>{t("history.more")}</Button>
      ) : null}
    </section>
  );
}
