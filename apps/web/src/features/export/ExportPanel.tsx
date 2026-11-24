// Save a version and download the workbook (docs/UX_SPEC.md F6): the export report is shown before
// the person trusts the file in another program.
import type { CompatItem, CompatibilityReport, SheetMeta } from "@contracts";
import { useEffect, useState } from "react";
import { errorKey } from "@/api/errors";
import { downloadUrl, exportReport, saveWorkbook, startExport } from "@/api/panels";
import { useJob } from "@/api/hooks";
import { Button } from "@/components/Button";
import { useT } from "@/i18n";
import { useUi } from "@/state/ui";

export function ExportPanel({ workbookId, sheet, onClose }: { workbookId: string; sheet: SheetMeta; onClose: () => void }) {
  const t = useT();
  const push = useUi((s) => s.pushToast);
  const [jobId, setJobId] = useState<string>();
  const [format, setFormat] = useState<"xlsx" | "csv">("xlsx");
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const job = useJob(jobId);

  const run = (f: "xlsx" | "csv") => {
    setStarting(true);
    setProblem(null);
    setFormat(f);
    setJobId(undefined);
    startExport(workbookId, f, f === "csv" ? sheet.id : undefined).then(
      (j) => {
        setJobId(j.id);
        setStarting(false);
      },
      (e: unknown) => {
        setStarting(false);
        setProblem(t(errorKey(e)));
      },
    );
  };
  const save = () => {
    setStarting(true);
    setProblem(null);
    saveWorkbook(workbookId).then(
      () => {
        setStarting(false);
        push("info", t("export.saved"));
      },
      (e: unknown) => {
        setStarting(false);
        setProblem(t(errorKey(e)));
      },
    );
  };
  const status = job.data?.status;
  const busy = starting || (jobId !== undefined && status !== "succeeded" && status !== "failed");

  return (
    <section className="panel" aria-labelledby="export-title">
      <header className="panel-head">
        <h2 id="export-title">{t("export.title")}</h2>
        <Button onClick={onClose} aria-label={t("shell.panelClose")}>{t("shell.panelClose")}</Button>
      </header>
      <p className="muted">{t("export.help")}</p>
      <div className="panel-actions">
        <Button onClick={save} disabled={busy}>{t("export.save")}</Button>
        <Button variant="primary" onClick={() => run("xlsx")} disabled={busy}>{t("export.xlsx")}</Button>
        <Button onClick={() => run("csv")} disabled={busy}>{t("export.csv", { sheet: sheet.name })}</Button>
      </div>
      {busy && !problem ? <p role="status" className="muted">{t("export.working")}</p> : null}
      {problem ? <p role="alert">{problem}</p> : null}
      {status === "failed" ? <p role="alert">{t("export.failed")}</p> : null}
      {status === "succeeded" && job.data?.result_ref && jobId ? (
        <>
          <p>
            <a className="btn btn-primary" href={downloadUrl(job.data.result_ref)} download>
              {t("export.download", { format: format.toUpperCase() })}
            </a>
          </p>
          <ExportReport jobId={jobId} />
        </>
      ) : null}
    </section>
  );
}

function ExportReport({ jobId }: { jobId: string }) {
  const t = useT();
  const [report, setReport] = useState<CompatibilityReport | null | "none">(null);
  useEffect(() => {
    let live = true;
    exportReport(jobId).then(
      (r) => live && setReport(r),
      () => live && setReport("none"),
    );
    return () => {
      live = false;
    };
  }, [jobId]);
  if (report === null) return <p className="muted">{t("export.reportLoading")}</p>;
  if (report === "none") return null;
  const worse = report.items.filter((i: CompatItem) => i.status !== "supported");
  return (
    <div>
      <h3>{t("export.reportTitle")}</h3>
      <p>{t("export.reportSummary", { ok: report.summary.supported, partial: report.summary.partial, no: report.summary.unsupported })}</p>
      {worse.length === 0 ? <p className="muted">{t("export.reportClean")}</p> : (
        <ul className="op-list">
          {worse.map((i, n) => (
            <li key={`${i.code}-${n}`} className="op-item">
              <strong>{i.status === "partial" ? t("export.partial") : t("export.unsupported")}</strong>
              <span className="muted">{i.message}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
