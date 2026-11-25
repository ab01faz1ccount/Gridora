// Format toolbar: bold/italic/underline, font, size, colours, alignment, wrap and number format for the
// selected cells. It shows the look of the active cell; every button sends one change (one undo step).
import type { FormatChange, StyleInfo } from "@contracts";
import { useEffect, useRef } from "react";
import { Button } from "@/components/Button";
import { useT } from "@/i18n";

/** A short list of fonts that exist on most computers, plus the one the app ships (Vazirmatn). */
export const FONTS = ["Vazirmatn", "Tahoma", "Calibri", "Arial", "Times New Roman", "Courier New"];
export const SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36];
export const NUMBER_FORMATS = [
  ["", "format.nf.general"], ["0", "format.nf.integer"], ["0.00", "format.nf.decimal"], ["#,##0", "format.nf.thousands"],
  ["#,##0.00", "format.nf.thousandsDecimal"], ["0%", "format.nf.percent"], ["0.00%", "format.nf.percent2"],
  ["0.00E+00", "format.nf.scientific"], ["yyyy-mm-dd", "format.nf.date"],
] as const;

const ALIGN_KEY = { left: "format.align.left", center: "format.align.center", right: "format.align.right" } as const;

/** A colour box that sends its value when the picker closes (not on every drag step). */
function ColorBox({ label, value, onPick }: { label: string; value: string; onPick: (hex: string) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const cb = useRef(onPick);
  useEffect(() => {
    cb.current = onPick;
  });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fn = () => cb.current(el.value.toUpperCase());
    el.addEventListener("change", fn);
    return () => el.removeEventListener("change", fn);
  }, []);
  useEffect(() => {
    if (ref.current) ref.current.value = value;
  }, [value]);
  return <input ref={ref} type="color" className="wbs-color" aria-label={label} title={label} defaultValue={value} />;
}

export function FormatBar({ look, onChange, disabled }: {
  look: StyleInfo | undefined; onChange: (change: FormatChange) => void; disabled?: boolean;
}) {
  const t = useT();
  const font = look?.font_name ?? "";
  const nf = look?.number_format ?? "";
  const known = NUMBER_FORMATS.some(([c]) => (c as string) === nf);
  return (
    <div className="wbs-format" role="toolbar" aria-label={t("format.label")}>
      <select aria-label={t("format.font")} value={font} disabled={disabled}
        onChange={(e) => onChange({ font_name: e.target.value || null })}>
        <option value="">{t("format.fontDefault")}</option>
        {FONTS.includes(font) || !font ? null : <option value={font}>{font}</option>}
        {FONTS.map((f) => <option key={f} value={f} style={{ fontFamily: f }}>{f}</option>)}
      </select>
      <select aria-label={t("format.size")} value={look?.font_size ?? ""} disabled={disabled}
        onChange={(e) => onChange({ font_size: e.target.value ? Number(e.target.value) : null })}>
        <option value="">{t("format.sizeDefault")}</option>
        {look?.font_size && !SIZES.includes(look.font_size) ? <option value={look.font_size}>{look.font_size}</option> : null}
        {SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <Button onClick={() => onChange({ bold: !look?.bold })} aria-pressed={look?.bold ?? false} aria-label={t("format.bold")}
        title={t("format.bold")} disabled={disabled}><b>{t("format.glyph.bold")}</b></Button>
      <Button onClick={() => onChange({ italic: !look?.italic })} aria-pressed={look?.italic ?? false} aria-label={t("format.italic")}
        title={t("format.italic")} disabled={disabled}><i>{t("format.glyph.italic")}</i></Button>
      <Button onClick={() => onChange({ underline: !look?.underline })} aria-pressed={look?.underline ?? false}
        aria-label={t("format.underline")} title={t("format.underline")} disabled={disabled}><u>{t("format.glyph.underline")}</u></Button>
      <ColorBox label={t("format.textColor")} value={look?.font_color ?? "#000000"} onPick={(hex) => onChange({ font_color: hex })} />
      <ColorBox label={t("format.fillColor")} value={look?.fill_color ?? "#FFFFFF"} onPick={(hex) => onChange({ fill_color: hex })} />
      <Button onClick={() => onChange({ fill_color: null, font_color: null })} aria-label={t("format.noColors")}
        title={t("format.noColors")} disabled={disabled}>◌</Button>
      {(["left", "center", "right"] as const).map((a) => (
        <Button key={a} onClick={() => onChange({ halign: look?.halign === a ? null : a })} aria-pressed={look?.halign === a}
          aria-label={t(ALIGN_KEY[a])} title={t(ALIGN_KEY[a])} disabled={disabled}>
          {a === "left" ? "⇤" : a === "center" ? "↔" : "⇥"}
        </Button>
      ))}
      <Button onClick={() => onChange({ wrap: !look?.wrap })} aria-pressed={look?.wrap ?? false} aria-label={t("format.wrap")}
        title={t("format.wrap")} disabled={disabled}>↵</Button>
      <select aria-label={t("format.numberFormat")} value={known ? nf : "custom"} disabled={disabled}
        onChange={(e) => e.target.value !== "custom" && onChange({ number_format: e.target.value || null })}>
        {NUMBER_FORMATS.map(([code, key]) => <option key={code} value={code}>{t(key)}</option>)}
        {known ? null : <option value="custom">{t("format.nf.custom")}</option>}
      </select>
    </div>
  );
}
