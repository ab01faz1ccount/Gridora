import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePrefs } from "@/state/prefs";
import { FormatBar } from "./FormatBar";

beforeEach(() => usePrefs.setState({ digits: "latin", locale: "en" }));

describe("FormatBar", () => {
  it("toggles from the active cell's look", async () => {
    const onChange = vi.fn();
    render(<FormatBar look={{ id: 2, bold: true, italic: false, underline: false, strike: false, wrap: false, halign: "center" }} onChange={onChange} />);
    const bold = screen.getByRole("button", { name: "Bold" });
    expect(bold).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(bold);
    expect(onChange).toHaveBeenLastCalledWith({ bold: false });
    await userEvent.click(screen.getByRole("button", { name: "Italic" }));
    expect(onChange).toHaveBeenLastCalledWith({ italic: true });
    await userEvent.click(screen.getByRole("button", { name: "Centre" })); // pressing the active alignment clears it
    expect(onChange).toHaveBeenLastCalledWith({ halign: null });
    await userEvent.click(screen.getByRole("button", { name: "Align right" }));
    expect(onChange).toHaveBeenLastCalledWith({ halign: "right" });
  });

  it("offers a short safe font list and number formats", async () => {
    const onChange = vi.fn();
    render(<FormatBar look={undefined} onChange={onChange} />);
    await userEvent.selectOptions(screen.getByLabelText("Font"), "Vazirmatn");
    expect(onChange).toHaveBeenLastCalledWith({ font_name: "Vazirmatn" });
    await userEvent.selectOptions(screen.getByLabelText("Number format"), "0%");
    expect(onChange).toHaveBeenLastCalledWith({ number_format: "0%" });
    await userEvent.selectOptions(screen.getByLabelText("Number format"), "");
    expect(onChange).toHaveBeenLastCalledWith({ number_format: null });
    await userEvent.selectOptions(screen.getByLabelText("Font size"), "14");
    expect(onChange).toHaveBeenLastCalledWith({ font_size: 14 });
  });
});
