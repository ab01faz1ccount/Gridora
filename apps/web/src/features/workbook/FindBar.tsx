// Find (Ctrl+F): the server scans the sheet's shown text; Enter goes to the next match, Shift+Enter to the
// previous one, Escape closes. Persian and Arabic digit/letter forms match each other (done by the engine).
import { useEffect, useRef, useState } from "react";
import { errorKey } from "@/api/errors";
import { findInSheet, type FindOptions } from "@/api/panels";
import { Button } from "@/components/Button";
import { useT } from "@/i18n";

type Result = "idle" | "found" | "none" | "wrapped";

export function FindBar({ workbookId, sheetId, active, onGo, onClose }: {
  workbookId: string; sheetId: string; active: { r: number; c: number }; onGo: (r: number, c: number) => void; onClose: () => void;
}) {
  const t = useT();
  const input = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [opts, setOpts] = useState<FindOptions>({ matchCase: false, wholeCell: false, inFormulas: false });
  const [result, setResult] = useState<Result>("idle");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => input.current?.select(), []);

  const go = async (back: boolean) => {
    if (!q || busy) return;
    setBusy(true);
    setProblem(null);
    try {
      let hit: { r: number; c: number } | undefined;
      let wrapped = false;
      if (!back) {
        hit = (await findInSheet(workbookId, sheetId, q, opts, active, 1)).matches[0];
        if (!hit) {
          hit = (await findInSheet(workbookId, sheetId, q, opts, undefined, 1)).matches[0];
          wrapped = hit !== undefined;
        }
      } else {
        const all = (await findInSheet(workbookId, sheetId, q, opts, undefined, 1000)).matches;
        const before = all.filter((m) => m.r < active.r || (m.r === active.r && m.c < active.c));
        hit = before[before.length - 1] ?? all[all.length - 1];
        wrapped = hit !== undefined && before.length === 0;
      }
      if (hit) onGo(hit.r, hit.c);
      setResult(hit ? (wrapped ? "wrapped" : "found") : "none");
    } catch (e) {
      setProblem(t(errorKey(e)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="wbs-find" role="search" aria-label={t("find.label")}>
      <input ref={input} type="search" value={q} dir="auto" placeholder={t("find.placeholder")} aria-label={t("find.placeholder")}
        onChange={(e) => { setQ(e.target.value); setResult("idle"); }}
        onKeyDown={(e) => {
          if (e.nativeEvent.isComposing) return;
          if (e.key === "Enter") { e.preventDefault(); void go(e.shiftKey); }
          else if (e.key === "Escape") { e.preventDefault(); onClose(); }
        }} />
      <Button onClick={() => void go(true)} disabled={!q || busy} aria-label={t("find.prev")}>↑</Button>
      <Button onClick={() => void go(false)} disabled={!q || busy} aria-label={t("find.next")}>↓</Button>
      {([["matchCase", "find.matchCase"], ["wholeCell", "find.wholeCell"], ["inFormulas", "find.inFormulas"]] as const).map(([k, key]) => (
        <label key={k} className="check">
          <input type="checkbox" checked={opts[k]} onChange={(e) => { setOpts({ ...opts, [k]: e.target.checked }); setResult("idle"); }} /> {t(key)}
        </label>
      ))}
      <span role="status" className="muted">
        {result === "none" ? t("find.none") : result === "wrapped" ? t("find.wrapped") : ""}
      </span>
      {problem ? <span role="alert">{problem}</span> : null}
      <Button onClick={onClose} aria-label={t("find.close")}>✕</Button>
    </div>
  );
}
