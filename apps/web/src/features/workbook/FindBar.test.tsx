import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePrefs } from "@/state/prefs";
import { FindBar } from "./FindBar";

const findInSheet = vi.fn();
vi.mock("@/api/panels", () => ({ findInSheet: (...a: unknown[]) => findInSheet(...a) }));

const hit = (r: number, c: number) => ({ matches: [{ r, c }], truncated: false });
const none = { matches: [], truncated: false };

beforeEach(() => {
  usePrefs.setState({ digits: "latin", locale: "en" });
  findInSheet.mockReset();
});

function setup(active = { r: 2, c: 1 }) {
  const onGo = vi.fn();
  const onClose = vi.fn();
  render(<FindBar workbookId="w" sheetId="s" active={active} onGo={onGo} onClose={onClose} />);
  return { onGo, onClose, box: screen.getByPlaceholderText("Find…") };
}

describe("FindBar", () => {
  it("Enter asks for the first match after the active cell and goes there", async () => {
    findInSheet.mockResolvedValueOnce(hit(5, 0));
    const { onGo, box } = setup();
    await userEvent.type(box, "abc{Enter}");
    await waitFor(() => expect(onGo).toHaveBeenCalledWith(5, 0));
    expect(findInSheet.mock.calls[0]![5]).toBe(1);
    expect(findInSheet.mock.calls[0]![4]).toEqual({ r: 2, c: 1 });
  });

  it("wraps to the start when nothing follows, and says so", async () => {
    findInSheet.mockResolvedValueOnce(none).mockResolvedValueOnce(hit(0, 0));
    const { onGo, box } = setup();
    await userEvent.type(box, "abc{Enter}");
    await waitFor(() => expect(onGo).toHaveBeenCalledWith(0, 0));
    expect(screen.getByText("Back at the start")).toBeInTheDocument();
  });

  it("Shift+Enter goes to the last match before the active cell", async () => {
    findInSheet.mockResolvedValueOnce({ matches: [{ r: 0, c: 0 }, { r: 1, c: 3 }, { r: 4, c: 0 }], truncated: false });
    const { onGo, box } = setup();
    await userEvent.type(box, "abc{Shift>}{Enter}{/Shift}");
    await waitFor(() => expect(onGo).toHaveBeenCalledWith(1, 3));
  });

  it("says not found, and Escape closes", async () => {
    findInSheet.mockResolvedValue(none);
    const { onClose, box } = setup();
    await userEvent.type(box, "zzz{Enter}");
    expect(await screen.findByText("Not found")).toBeInTheDocument();
    await userEvent.type(box, "{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
