import type { CompatibilityReport, CompatItem } from "@contracts";
import { Button } from "@/components/Button";
import { useT } from "@/i18n";
import { formatNumber } from "@/i18n/format";
import { usePrefs } from "@/state/prefs";

const ORDER: CompatItem["status"][] = ["unsupported", "partial", "supported"];

/** The engine's statuses, grouped and never softened (docs/UX_SPEC.md section 6). */
export function CompatPanel({ report, onClose }: { report: CompatibilityReport; onClose: () => void }) {
  const t = useT();
  const digits = usePrefs((s) => s.digits);
  return (
    <section className="panel" aria-labelledby="compat-title">
      <header className="panel-head">
        <h2 id="compat-title">{t("compat.title")}</h2>
        <Button onClick={onClose} aria-label={t("compat.close")}>{t("shell.panelClose")}</Button>
      </header>
      {report.items.length === 0 ? <p className="muted">{t("compat.empty")}</p> : null}
      {ORDER.map((status) => {
        const items = report.items.filter((i) => i.status === status);
        if (items.length === 0) return null;
        return (
          <div key={status} className={`compat-group compat-${status}`}>
            <h3>
              {t(`compat.${status}`)} <span className="muted">({formatNumber(items.length, digits, 0)})</span>
            </h3>
            <ul>
              {items.map((i, n) => (
                <li key={`${i.code}-${i.location ?? ""}-${n}`}>
                  <div className="compat-msg" dir="auto">{i.message}</div>
                  <div className="muted compat-meta">
                    <bdi dir="ltr">{i.code}</bdi>
                    {i.location ? <> · {t("compat.location", { where: i.location })}</> : null}
                    {" · "}{i.preserved ? t("compat.kept") : t("compat.notKept")}
                    {" · "}{i.editable ? t("compat.editable") : t("compat.readOnly")}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      <p className="muted">{t("compat.messageNote")}</p>
    </section>
  );
}

export function attentionCount(report: CompatibilityReport | undefined): number {
  return report ? report.items.filter((i) => i.status !== "supported").length : 0;
}
