import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePrefs } from "@/state/prefs";
import { useUi } from "@/state/ui";
import { mockApi, ok } from "@/test/mockApi";
import { WorkbookPage } from "../workbook/WorkbookPage";

const SHEET = { id: "s1", name: "Sheet1", index: 0, visible: "visible", row_count: 50, col_count: 5, rtl: false };
const WORKBOOK = { id: "w1", file_id: "f1", name: "book", sheets: [SHEET], defined_names: [], date_system: "1900" };
const DESCRIPTOR = {
  type: "remove_duplicates",
  label: "ops.remove_duplicates.label",
  category: "cleaning",
  description: "ops.remove_duplicates.description",
  params_schema: { type: "object", properties: { keep: { type: "string", enum: ["first", "last"], default: "first" } } },
  targets: ["sheet_range"],
  destructive: true,
  supports_preview: false,
};
const CATALOG = {
  "ops.remove_duplicates.label": "Remove duplicates",
  "ops.remove_duplicates.description": "Keeps one of each repeated row",
  "ops.remove_duplicates.keywords": "duplicates, repeated",
  "ops.categories.cleaning": "Cleaning",
};

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(764);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(528);
  usePrefs.setState({ digits: "latin", locale: "en" });
  useUi.setState({ toasts: [], panel: null });
  mockApi({
    "GET /workbooks/w1": () => ok(WORKBOOK),
    "GET /workbooks/w1/sheets/s1/cells?r0=0&c0=0&rows=100&cols=26": () =>
      ok({ sheet_id: "s1", row0: 0, col0: 0, rows: 100, cols: 26, cells: [] }),
    "GET /documents/w1/history?limit=100": () => ok([]),
    "GET /operations": () => ok([DESCRIPTOR]),
    "GET /operations/i18n?locale=en": () => ok(CATALOG),
  });
});
afterEach(() => vi.restoreAllMocks());

describe("task bar and operation panel", () => {
  it("typing a word finds the task and opens its form with the destructive warning", async () => {
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><WorkbookPage id="w1" /></QueryClientProvider>);
    const box = await screen.findByRole("searchbox");
    await user.type(box, "duplic");
    const item = await screen.findByRole("button", { name: /Remove duplicates/ });
    expect(screen.getAllByText("Changes the data").length).toBeGreaterThan(0);
    await user.click(item);
    await waitFor(() => expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument());
  });
});
