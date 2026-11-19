import type { Job } from "@contracts";
import { useEffect, useState } from "react";
import { ApiError } from "@/api/client";
import { errorKey } from "@/api/errors";
import { openFile, useJob } from "@/api/hooks";
import { Button } from "@/components/Button";
import { useT } from "@/i18n";
import { formatNumber } from "@/i18n/format";
import { useImports, type ImportEntry } from "@/state/imports";
import { usePrefs } from "@/state/prefs";
import { attentionCount } from "./CompatPanel";
import { formatSize } from "./format";

function jobError(job: Job): ApiError {
  const e = job.error;
  return new ApiError({ code: e?.code ?? "internal_error", message: e?.message ?? "", status: 0, details: e?.details });
}

export function ImportCard({
  entry,
  onOpenWorkbook,
  onShowReport,
}: {
  entry: ImportEntry;
  onOpenWorkbook: (workbookId: string) => void;
  onShowReport: (workbookId: string) => void;
}) {
  const t = useT();
  const digits = usePrefs((s) => s.digits);
  const { cancel, dismiss, jobFinished } = useImports();
  const job = useJob(entry.phase === "processing" ? entry.jobId : undefined);
  const [slow, setSlow] = useState(false);

  // "this may take a minute" after 5 s
  useEffect(() => {
    if (entry.phase !== "processing" && entry.phase !== "uploading") return;
    const timer = setTimeout(() => setSlow(true), 5000);
    return () => clearTimeout(timer);
  }, [entry.phase]);

  // the job finished: learn what the import found, then offer open / report
  const status = job.data?.status;
  useEffect(() => {
    if (!job.data || entry.phase !== "processing") return;
    if (job.data.status === "failed") {
      jobFinished(entry.key, false, jobError(job.data));
    } else if (job.data.status === "succeeded" && job.data.result_ref && entry.fileId) {
      const wb = job.data.result_ref;
      void openFile(entry.fileId).then(
        (w) => jobFinished(entry.key, true, undefined, { workbookId: wb, attention: attentionCount(w.compat) }),
        () => jobFinished(entry.key, true, undefined, { workbookId: wb }),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  const percent = entry.size > 0 ? Math.min(100, Math.round((entry.loaded / entry.size) * 100)) : 0;
  const head = (
    <div className="import-head">
      <strong dir="auto"><bdi>{entry.name}</bdi></strong>
      <span className="muted">{t("import.sizeLine", { size: formatSize(entry.size, digits) })}</span>
    </div>
  );

  if (entry.phase === "failed") {
    return (
      <li className="card import-card import-failed" role="alert">
        {head}
        <p>{t("import.failed")} {t(errorKey(entry.error))}</p>
        <div className="actions"><Button onClick={() => dismiss(entry.key)}>{t("import.dismiss")}</Button></div>
      </li>
    );
  }
  if (entry.phase === "done") {
    const wb = entry.workbookId;
    const attention = entry.attention ?? 0;
    return (
      <li className="card import-card" role="status">
        {head}
        <p>
          {attention > 0
            ? t("import.openedAttention", { count: formatNumber(attention, digits, 0) })
            : t("import.openedClean")}
        </p>
        <div className="actions">
          {wb ? <Button variant="primary" onClick={() => onOpenWorkbook(wb)}>{t("import.open")}</Button> : null}
          {wb && attention > 0 ? (
            <Button onClick={() => onShowReport(wb)}>{t("import.showReport")}</Button>
          ) : null}
          <Button onClick={() => dismiss(entry.key)}>{t("import.dismiss")}</Button>
        </div>
      </li>
    );
  }
  return (
    <li className="card import-card" aria-busy="true">
      {head}
      {entry.phase === "uploading" ? (
        <>
          <progress max={100} value={percent} aria-label={t("import.uploading", { percent: "" })} />
          <p className="muted">{t("import.uploading", { percent: `${formatNumber(percent, digits, 0)}٪` })}</p>
          <div className="actions"><Button onClick={() => cancel(entry.key)}>{t("import.cancel")}</Button></div>
        </>
      ) : (
        <>
          <progress aria-label={t("import.processing")} />
          <p className="muted">{t("import.processing")}{slow ? ` ${t("import.slow")}` : ""}</p>
          <p className="muted">{t("import.cannotCancelJob")}</p>
        </>
      )}
    </li>
  );
}
