// Saved tools (docs/UX_SPEC.md F7): run a tool someone built from a pipeline on the selected range.
import type { SheetMeta, Tool } from "@contracts";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "@/api/client";
import { errorKey } from "@/api/errors";
import { deleteTool, useTools } from "@/api/panels";
import { Button } from "@/components/Button";
import type { WorkbookEditor } from "@/grid/editing";
import type { RangeBounds } from "@/grid/selection";
import { useT } from "@/i18n";
import { useUi } from "@/state/ui";

export function ToolsPanel({ workbookId, sheet, bounds, editor, onClose }: {
  workbookId: string; sheet: SheetMeta; bounds: RangeBounds; editor: WorkbookEditor; onClose: () => void;
}) {
  const t = useT();
  const tools = useTools();
  const [open, setOpen] = useState<string>();
  const qc = useQueryClient();
  return (
    <section className="panel" aria-labelledby="tools-title">
      <header className="panel-head">
        <h2 id="tools-title">{t("tools.title")}</h2>
        <Button onClick={onClose} aria-label={t("shell.panelClose")}>{t("shell.panelClose")}</Button>
      </header>
      <p className="muted">{t("tools.help")}</p>
      {tools.isError ? <p role="alert">{t("tools.loadError")}</p> : null}
      {tools.data?.length === 0 ? <p className="muted">{t("tools.none")}</p> : null}
      <ul className="op-list">
        {(tools.data ?? []).map((tool) => (
          <li key={tool.id} className="op-item">
            <button type="button" className="link-btn" aria-expanded={open === tool.id} onClick={() => setOpen(open === tool.id ? undefined : tool.id)}>
              <strong><bdi>{tool.name}</bdi></strong> <span className="muted">{tool.description}</span>
            </button>
            {open === tool.id ? (
              <RunTool tool={tool} workbookId={workbookId} sheet={sheet} bounds={bounds} editor={editor}
                onDeleted={() => void qc.invalidateQueries({ queryKey: ["tools"] })} onDone={onClose} />
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function RunTool({ tool, workbookId, sheet, bounds, editor, onDeleted, onDone }: {
  tool: Tool; workbookId: string; sheet: SheetMeta; bounds: RangeBounds; editor: WorkbookEditor; onDeleted: () => void; onDone: () => void;
}) {
  const t = useT();
  const push = useUi((s) => s.pushToast);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const multi = bounds.r1 > bounds.r0 || bounds.c1 > bounds.c0;
  const missing = tool.inputs.some((i) => i.required && !(inputs[i.name] ?? "").trim());
  const run = () => {
    setRunning(true);
    setProblem(null);
    const range = multi
      ? { sheet_id: sheet.id, r0: bounds.r0, c0: bounds.c0, r1: bounds.r1, c1: bounds.c1 }
      : { sheet_id: sheet.id, r0: 0, c0: 0, r1: Math.max(0, sheet.row_count - 1), c1: Math.max(0, sheet.col_count - 1) };
    editor.write(`/tools/${tool.id}/run`, (base_seq) => ({
      workbook_id: workbookId, target: { kind: "sheet_range", range }, inputs, base_seq, confirm_destructive: confirm,
    })).then(
      () => { push("info", t("tools.done", { name: tool.name })); onDone(); },
      (e: unknown) => {
        setRunning(false);
        if (e instanceof ApiError && e.details.some((d) => d.code === "operation.confirm_required")) setConfirm(true);
        else if (!(e instanceof ApiError && e.code === "version_conflict")) setProblem(t(errorKey(e)));
      },
    );
  };
  return (
    <form className="panel" onSubmit={(e) => { e.preventDefault(); run(); }}>
      <p className="muted">{multi ? t("tools.onSelection") : t("tools.onSheet")}</p>
      {tool.inputs.map((i) => (
        <label key={i.name} className="field">{i.label}{i.required ? " *" : ""}
          <input value={inputs[i.name] ?? ""} dir="auto" onChange={(e) => setInputs({ ...inputs, [i.name]: e.target.value })} />
        </label>
      ))}
      {confirm ? <p role="alert">{t("tools.confirm")}</p> : null}
      {problem ? <p role="alert">{problem}</p> : null}
      <div className="panel-actions">
        <Button type="submit" variant={confirm ? "danger" : "primary"} disabled={running || missing}>
          {running ? t("opPanel.applying") : confirm ? t("tools.runConfirm") : t("tools.run")}
        </Button>
        <Button variant="danger" onClick={() => tool.id && void deleteTool(tool.id).then(onDeleted)}>{t("tools.delete")}</Button>
      </div>
    </form>
  );
}
