import { describe, expect, it } from "vitest";
import { dedupe, columnNames, headerName } from "./columns";
import { cleanValue, defaultFor, fieldPath, isVisible, orderedKeys, resolve, unionOf, type Schema } from "./schemaForm";
import { normalizeText, opEntries, searchOps } from "./searchOps";

const SORT: Schema = {
  type: "object",
  required: ["keys"],
  properties: {
    note: { type: "string", title: "n" },
    has_header: { type: "boolean", default: true, "x-gridora-order": 0 },
    keys: {
      type: "array", minItems: 1, "x-gridora-order": 1,
      items: {
        type: "object", required: ["column"],
        properties: {
          column: { type: "string", "x-gridora-column": true },
          direction: { type: "string", enum: ["asc", "desc"], default: "asc" },
        },
      },
    },
  },
};

describe("defaults and cleaning", () => {
  it("starts with one empty sort key and the declared defaults", () => {
    expect(defaultFor(SORT, SORT)).toEqual({ has_header: true, keys: [{ column: "", direction: "asc" }] });
  });
  it("orders by x-gridora-order, then declaration order", () => {
    expect(orderedKeys(SORT)).toEqual(["has_header", "keys", "note"]);
  });
  it("leaves out empty optional strings but keeps required ones", () => {
    const v = { has_header: true, note: "", keys: [{ column: "", direction: "asc" }] };
    expect(cleanValue(SORT, SORT, v)).toEqual({ has_header: true, keys: [{ column: "", direction: "asc" }] });
  });
  it("hides fields by visible-if and drops them from the result", () => {
    const schema: Schema = {
      type: "object",
      properties: {
        mode: { type: "string", enum: ["a", "b"], default: "a" },
        only_b: { type: "string", "x-gridora-visible-if": { property: "mode", equals: "b" } },
      },
    };
    expect(isVisible(resolve({ "x-gridora-visible-if": { property: "mode", equals: "b" } }, schema), { mode: "a" })).toBe(false);
    expect(cleanValue(schema, schema, { mode: "a", only_b: "x" })).toEqual({ mode: "a" });
    expect(cleanValue(schema, schema, { mode: "b", only_b: "x" })).toEqual({ mode: "b", only_b: "x" });
  });
  it("nullable values become null when empty", () => {
    const schema: Schema = { type: "object", properties: { n: { anyOf: [{ type: "integer" }, { type: "null" }] } } };
    expect(defaultFor(schema, schema)).toEqual({});
    expect(cleanValue(schema, schema, { n: "" })).toEqual({ n: null });
    expect(cleanValue(schema, schema, { n: 3 })).toEqual({ n: 3 });
  });
  it("finds the discriminator of a union and follows $ref", () => {
    const root: Schema = {
      $defs: { A: { type: "object", properties: { kind: { const: "a" }, x: { type: "string" } } } },
      anyOf: [{ $ref: "#/$defs/A" }, { type: "object", properties: { kind: { const: "b" } } }],
    };
    const u = unionOf(root, root);
    expect(u?.discriminator).toBe("kind");
    expect(u?.branches.map((b) => b.value)).toEqual(["a", "b"]);
    expect(defaultFor(root, root)).toEqual({ kind: "a" });
  });
  it("maps a validation path to a path inside params", () => {
    expect(fieldPath("/params/keys/0/column")).toBe("/keys/0/column");
    expect(fieldPath("/target/kind")).toBeNull();
  });
});

describe("column names", () => {
  it("follows the header row the way the server does", () => {
    const cells = [
      { r: 0, c: 0, v: { k: "str" as const, s: " نام " } },
      { r: 0, c: 1, v: { k: "num" as const, n: 2024 } },
      undefined,
      { r: 0, c: 3, v: { k: "str" as const, s: "نام" } },
    ];
    expect(columnNames(4, true, (i) => cells[i])).toEqual(["نام", "2024", "column_3", "نام_2"]);
    expect(columnNames(2, false, () => undefined)).toEqual(["column_1", "column_2"]);
    expect(headerName({ r: 0, c: 0, v: { k: "bool", b: true } }, 0)).toBe("TRUE");
    expect(dedupe(["a", "a", "a"])).toEqual(["a", "a_2", "a_3"]);
  });
});

describe("task search", () => {
  const descriptors = [
    { type: "remove_duplicates", label: "ops.remove_duplicates.label", category: "clean", description: "ops.remove_duplicates.description", params_schema: {}, targets: ["sheet_range" as const], destructive: true, supports_preview: true },
    { type: "sort", label: "ops.sort.label", category: "order", description: "ops.sort.description", params_schema: {}, targets: ["sheet_range" as const], destructive: false, supports_preview: true },
  ];
  const catalog = {
    "ops.remove_duplicates.label": "حذف تکراری‌ها",
    "ops.remove_duplicates.description": "ردیف‌های تکراری را حذف می‌کند.",
    "ops.remove_duplicates.keywords": "تکراری، ردیف مشابه، یکتا",
    "ops.sort.label": "مرتب‌سازی",
    "ops.sort.description": "ردیف‌ها را مرتب می‌کند.",
    "ops.sort.keywords": "مرتب، ترتیب، الفبایی",
    "ops.categories.clean": "پاک‌سازی",
    "ops.categories.order": "ترتیب",
  };
  const entries = opEntries(descriptors, catalog);
  it("normalizes letters, digits and half-spaces", () => {
    expect(normalizeText("كتاب ي ۱۲۳ ٤٥")).toBe("کتاب ی 123 45");
    expect(normalizeText("می‌خواهم")).toBe(normalizeText("میخواهم"));
  });
  it("finds an operation by a task phrase, with either spelling of the letters", () => {
    expect(searchOps(entries, "تکراری")[0]?.type).toBe("remove_duplicates");
    expect(searchOps(entries, "ردیف مشابه")[0]?.type).toBe("remove_duplicates");
    expect(searchOps(entries, "الفبايي")[0]?.type).toBe("sort");
    expect(searchOps(entries, "هیچ چیز")).toEqual([]);
  });
  it("an empty query lists everything", () => {
    expect(searchOps(entries, "  ")).toHaveLength(2);
  });
});
