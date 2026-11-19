import { describe, expect, it } from "vitest";
import { catalogs } from "@/i18n";
import { ApiError } from "./client";
import { errorKey, isTooLargeForHistory, reasonOf } from "./errors";

const err = (code: string, reasons: string[] = []) =>
  new ApiError({ code, message: "x", status: 400, details: reasons.map((c) => ({ code: c, message: "m" })) });

describe("errorKey: specific reasons win over generic codes", () => {
  it("F4: too_large_for_history gets the exact UX-spec sentence (and no code is shown)", () => {
    const e = err("operation_conflict", ["too_large_for_history"]);
    expect(errorKey(e)).toBe("error.reason.too_large_for_history");
    expect(isTooLargeForHistory(e)).toBe(true);
    expect(catalogs.fa["error.reason.too_large_for_history"]).toBe(
      "این کار روی کل برگه خیلی بزرگ است و واگرد ندارد. می‌توانید آن را به «جدول داده» تبدیل کنید و آنجا انجام دهید.",
    );
    expect(catalogs.fa["error.reason.too_large_for_history"]).not.toMatch(/too_large|operation_conflict/);
  });

  it("F1: legacy .xls, encrypted and strict-OOXML each have a plain message that says what to do", () => {
    for (const reason of ["xlsx.legacy_xls", "xlsx.encrypted", "xlsx.encrypted_or_legacy", "xlsx.strict_ooxml"]) {
      const e = err("unsupported_workbook", [reason]);
      const key = errorKey(e);
      expect(key).toMatch(/^error\.reason\./);
      expect(catalogs.fa[key]).toMatch(/[\u0600-\u06FF]/);
      expect(catalogs.fa[key]).toMatch(/xlsx|اکسل|رمز/);
    }
    expect(catalogs.fa["error.reason.legacy_xls"]).toContain("ذخیره");
  });

  it("falls back to the generic code, then to the generic message", () => {
    expect(errorKey(err("not_found"))).toBe("error.not_found");
    expect(errorKey(err("not_found", ["some.unknown.reason"]))).toBe("error.not_found");
    expect(errorKey(err("made_up"))).toBe("error.generic");
    expect(errorKey(new Error("x"))).toBe("error.generic");
    expect(errorKey(undefined)).toBe("error.generic");
  });

  it("reasonOf only reports reasons that have a message", () => {
    expect(reasonOf(err("validation_failed", ["nothing", "edit.out_of_range"]))).toBe("edit.out_of_range");
    expect(reasonOf(err("validation_failed"))).toBeUndefined();
    expect(isTooLargeForHistory(err("operation_conflict"))).toBe(false);
  });

  it("every reason message exists in both languages", () => {
    for (const k of Object.keys(catalogs.fa).filter((k) => k.startsWith("error.reason."))) {
      expect(catalogs.en[k as keyof typeof catalogs.en], k).toBeTruthy();
    }
  });
});
