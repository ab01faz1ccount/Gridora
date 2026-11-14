import { ERROR_CODES } from "@contracts";
import { describe, expect, it } from "vitest";
import { catalogs, DIRECTION, MESSAGE_KEYS, translate, type MessageKey } from "./index";

const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("catalogs", () => {
  it("fa and en have exactly the same keys", () => {
    expect(Object.keys(catalogs.en).sort()).toEqual(Object.keys(catalogs.fa).sort());
  });

  it("no message is empty and placeholders match between languages", () => {
    for (const key of MESSAGE_KEYS) {
      expect(catalogs.fa[key].trim(), key).not.toBe("");
      expect(catalogs.en[key].trim(), key).not.toBe("");
      expect(placeholders(catalogs.fa[key]), key).toEqual(placeholders(catalogs.en[key]));
    }
  });

  it("every contract error code (and network) has a message in both languages", () => {
    for (const code of [...ERROR_CODES, "network"]) {
      expect(MESSAGE_KEYS, code).toContain(`error.${code}` as MessageKey);
    }
  });

  it("the Persian catalog really is Persian where it should be", () => {
    expect(catalogs.fa["auth.submit"]).toMatch(/[\u0600-\u06FF]/);
    expect(catalogs.en["auth.submit"]).not.toMatch(/[\u0600-\u06FF]/);
  });
});

describe("translate", () => {
  it("interpolates and leaves unknown placeholders visible", () => {
    expect(translate("en", "auth.rateLimited", { seconds: 30 })).toContain("30");
    expect(translate("en", "workspaces.createdAt", {})).toContain("{date}");
  });
  it("directions", () => {
    expect(DIRECTION).toEqual({ fa: "rtl", en: "ltr" });
  });
});
