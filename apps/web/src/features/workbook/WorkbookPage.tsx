import type { SheetMeta, Workbook } from "@contracts";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, ApiError } from "@/api/client";
import { errorKey } from "@/api/errors";
import { Button } from "@/components/Button";
import { navigate } from "@/app/router";
import { Grid } from "@/grid/Grid";
import { sheetDataSource } from "@/grid/datasource";
import { useT } from "@/i18n";
import { formatNumber } from "@/i18n/format";
import { usePrefs } from "@/state/prefs";

export function useWorkbook(id: string) {
  return useQuery({
    queryKey: ["workbook", id],
    queryFn: () => api.get<Workbook>(`/workbooks/${id}`),
    retry: false,
  });
}

export function WorkbookPage({ id }: { id: string }) {
  const t = useT();
  const digits = usePrefs((s) => s.digits);
  const wb = useWorkbook(id);
  const [sheetId, setSheetId] = useState<string | null>(null);

  const visible: SheetMeta[] = useMemo(
    () => (wb.data?.sheets ?? []).filter((s) => s.visible === "visible"),
    [wb.data],
  );
  const sheet = visible.find((s) => s.id === sheetId) ?? visible[0];
  const source = useMemo(
    () => (sheet ? sheetDataSource(id, sheet.id, sheet.row_count, sheet.col_count) : null),
    [id, sheet],
  );

  if (wb.isPending) return <p>{t("workbook.loading")}</p>;
  if (wb.isError) {
    const notFound = wb.error instanceof ApiError && wb.error.code === "not_found";
    return (
      <div role="alert">
        <p>{notFound ? t("workbook.notFound") : t(errorKey(wb.error))}</p>
        <Button onClick={() => navigate("/workspaces")}>{t("workbook.back")}</Button>
      </div>
    );
  }
  if (!sheet || !source) return <p>{t("workbook.noSheets")}</p>;

  return (
    <section aria-label={wb.data.name}>
      <div className="wb-bar">
        <Button onClick={() => navigate("/workspaces")}>{t("workbook.back")}</Button>
        <h1><bdi>{wb.data.name}</bdi></h1>
        <span className="muted">
          {t("workbook.dimensions", {
            rows: formatNumber(sheet.row_count, digits, 0),
            cols: formatNumber(sheet.col_count, digits, 0),
          })}
        </span>
      </div>
      <div className="gv-host">
        <Grid key={`${id}:${sheet.id}`} source={source} rtl={sheet.rtl} />
      </div>
      <div role="tablist" aria-label={t("grid.sheetTabs")} className="sheet-tabs">
        {visible.map((s) => (
          <button key={s.id} type="button" role="tab" aria-selected={s.id === sheet.id}
            className={"sheet-tab" + (s.id === sheet.id ? " sheet-tab-active" : "")}
            onClick={() => setSheetId(s.id)}>
            <bdi>{s.name}</bdi>
          </button>
        ))}
      </div>
    </section>
  );
}
