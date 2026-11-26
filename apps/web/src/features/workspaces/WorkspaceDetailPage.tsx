import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "@/api/client";
import { errorKey } from "@/api/errors";
import { openFile, useFiles, useWorkspace } from "@/api/hooks";
import { navigate } from "@/app/router";
import { Button } from "@/components/Button";
import { DropZone } from "@/features/import/DropZone";
import { ImportCard } from "@/features/import/ImportCard";
import { formatSize } from "@/features/import/format";
import { useT } from "@/i18n";
import { formatDate } from "@/i18n/format";
import { useImports } from "@/state/imports";
import { usePrefs } from "@/state/prefs";
import { useUi } from "@/state/ui";

export function WorkspaceDetailPage({ id }: { id: string }) {
  const t = useT();
  const { locale, digits, calendar } = usePrefs();
  const qc = useQueryClient();
  const push = useUi((s) => s.pushToast);
  const setPanel = useUi((s) => s.setPanel);
  const ws = useWorkspace(id);
  const files = useFiles(id);
  const entries = useImports((s) => s.entries).filter((e) => e.workspaceId === id);
  const start = useImports((s) => s.start);
  const createNew = useImports((s) => s.createNew);
  const [naming, setNaming] = useState<string | null>(null);

  const refreshFiles = () => void qc.invalidateQueries({ queryKey: ["files", id] });
  const openWorkbook = (workbookId: string) => navigate(`/workbooks/${workbookId}`);
  const showReport = (workbookId: string) => {
    setPanel("report");
    navigate(`/workbooks/${workbookId}`);
  };

  async function openStored(fileId: string) {
    try {
      const wb = await openFile(fileId);
      openWorkbook(wb.id);
    } catch (e) {
      push("error", t(errorKey(e instanceof ApiError ? e : undefined)));
    }
  }

  if (ws.isPending) return <p>{t("common.loading")}</p>;
  if (ws.isError) {
    return (
      <div role="alert">
        <p>{t(errorKey(ws.error))}</p>
        <Button onClick={() => navigate("/workspaces")}>{t("workbook.back")}</Button>
      </div>
    );
  }

  return (
    <section aria-labelledby="wsd-title">
      <div className="wb-bar">
        <Button onClick={() => navigate("/workspaces")}>{t("workbook.back")}</Button>
        <h1 id="wsd-title"><bdi>{ws.data.name}</bdi></h1>
      </div>

      {naming === null ? (
        <Button variant="primary" onClick={() => setNaming(t("newFile.defaultName"))}>{t("newFile.button")}</Button>
      ) : (
        <form className="wbs-task" onSubmit={(e) => {
          e.preventDefault();
          if (naming.trim()) createNew(id, naming.trim(), refreshFiles);
          setNaming(null);
        }}>
          <label className="field">{t("newFile.name")}
            <input value={naming} onChange={(e) => setNaming(e.target.value)} dir="auto" maxLength={120} autoFocus />
          </label>
          <Button type="submit" variant="primary" disabled={!naming.trim()}>{t("newFile.create")}</Button>
          <Button onClick={() => setNaming(null)}>{t("common.cancel")}</Button>
        </form>
      )}

      <DropZone onFiles={(fs) => fs.forEach((f) => start(id, f, refreshFiles))} />

      {entries.length > 0 ? (
        <ul className="import-list" aria-live="polite">
          {entries.map((e) => (
            <ImportCard key={e.key} entry={e} onOpenWorkbook={openWorkbook} onShowReport={showReport} />
          ))}
        </ul>
      ) : null}

      <h2>{t("import.filesTitle")}</h2>
      {files.data && files.data.length === 0 ? <p className="muted">{t("import.noFiles")}</p> : null}
      {files.data && files.data.length > 0 ? (
        <ul className="ws-list">
          {files.data.map((f) => (
            <li key={f.id} className="card ws-item">
              <div>
                <strong dir="auto"><bdi>{f.display_name}</bdi></strong>
                <div className="muted">
                  {formatSize(f.size_bytes, digits)} · {formatDate(f.created_at, { calendar, digits, locale })}
                </div>
              </div>
              <div className="actions">
                <Button onClick={() => void openStored(f.id)}>{t("import.openFile")}</Button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
