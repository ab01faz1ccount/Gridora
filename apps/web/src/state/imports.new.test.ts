import { describe, expect, it } from "vitest";
import { mockApi, ok } from "@/test/mockApi";
import { useImports } from "./imports";

describe("creating a new empty file", () => {
  it("asks the server for it and shows a card that waits for the import job", async () => {
    const api = mockApi({
      "POST /workspaces/w1/files/new": () =>
        ok({ file: { id: "f9", display_name: "جدول جدید.xlsx" }, job_id: "j9" }),
    });
    let created = 0;
    useImports.setState({ entries: [] });
    useImports.getState().createNew("w1", "جدول جدید", () => created++);
    expect(useImports.getState().entries[0]?.phase).toBe("processing");
    await new Promise((r) => setTimeout(r, 20));
    const e = useImports.getState().entries[0];
    expect(e).toMatchObject({ jobId: "j9", fileId: "f9", name: "جدول جدید.xlsx" });
    expect(api.calls[0]?.body).toEqual({ name: "جدول جدید" });
    expect(created).toBe(1);
  });
});
