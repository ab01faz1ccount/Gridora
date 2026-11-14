import { afterEach, describe, expect, it, vi } from "vitest";
import { readPrefs, reloadPrefs, usePrefs } from "./prefs";

afterEach(() => vi.restoreAllMocks());

describe("prefs", () => {
  it("defaults to Persian, RTL-first, Persian digits, Gregorian", () => {
    expect(readPrefs()).toEqual({ locale: "fa", digits: "persian", calendar: "gregorian" });
  });

  it("persists a change and restores it", () => {
    usePrefs.getState().set({ locale: "en", calendar: "jalali" });
    expect(JSON.parse(localStorage.getItem("gridora.prefs") ?? "{}")).toMatchObject({
      locale: "en",
      calendar: "jalali",
    });
    reloadPrefs();
    expect(usePrefs.getState().locale).toBe("en");
  });

  it.each(["{not json", "null", '"str"', '{"locale":"xx","digits":5}'])(
    "falls back to defaults for corrupt storage %s",
    (raw) => {
      localStorage.setItem("gridora.prefs", raw);
      expect(readPrefs()).toEqual({ locale: "fa", digits: "persian", calendar: "gregorian" });
    },
  );

  it("keeps working when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("full");
    });
    expect(readPrefs().locale).toBe("fa");
    usePrefs.getState().set({ digits: "latin" });
    expect(usePrefs.getState().digits).toBe("latin"); // in-memory value still applies
  });
});
