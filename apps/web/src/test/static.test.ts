// Static guards from apps/PLAN.md 3.4: no hard-coded UI strings, no physical left/right CSS.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");

function walk(dir: string, exts: string[]): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) return walk(p, exts);
    return exts.some((e) => p.endsWith(e)) && !p.endsWith(".test.ts") && !p.endsWith(".test.tsx")
      ? [p]
      : [];
  });
}

const VISIBLE_ATTRS = new Set(["title", "placeholder", "aria-label", "alt", "label", "aria-description"]);
const HAS_LETTER = /\p{L}/u;

export function findLiteralStrings(source: string, file = "x.tsx"): string[] {
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found: string[] = [];
  const visit = (n: ts.Node) => {
    if (ts.isJsxText(n) && HAS_LETTER.test(n.text)) found.push(n.text.trim());
    if (
      ts.isJsxAttribute(n) &&
      VISIBLE_ATTRS.has(n.name.getText(sf)) &&
      n.initializer &&
      ts.isStringLiteral(n.initializer)
    ) {
      found.push(`${n.name.getText(sf)}="${n.initializer.text}"`);
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return found;
}

describe("no hard-coded user-visible strings in components", () => {
  it("the scanner itself catches text and attributes (guard the guard)", () => {
    expect(findLiteralStrings("const a = <p>Hello</p>;")).toEqual(["Hello"]);
    expect(findLiteralStrings('const a = <input placeholder="Name" />;')).toEqual(['placeholder="Name"']);
    expect(findLiteralStrings("const a = <p>سلام</p>;")).toEqual(["سلام"]);
    expect(findLiteralStrings("const a = <p>{t('x')}</p>;")).toEqual([]);
    expect(findLiteralStrings('const a = <option value="latin">{t("a")}</option>;')).toEqual([]);
  });

  it("every component uses the catalog", () => {
    const bad: Record<string, string[]> = {};
    for (const f of walk(SRC, [".tsx"])) {
      const hits = findLiteralStrings(readFileSync(f, "utf8"), f);
      if (hits.length) bad[f.replace(SRC, "src")] = hits;
    }
    expect(bad).toEqual({});
  });
});

describe("CSS uses logical properties", () => {
  const PHYSICAL =
    /(^|[;{\s])(margin|padding|border)-(left|right)\b|(^|[;{\s])(left|right)\s*:|text-align\s*:\s*(left|right)|float\s*:|border-(top|bottom)-(left|right)-radius|(^|[;{\s])(width|height|min-width|max-width|min-height|max-height)\s*:/m;

  it("the pattern catches what it should", () => {
    for (const bad of ["margin-left: 1px", "a{left: 0}", "text-align: right", "padding-right:2px", "float: left", "width: 10px"]) {
      expect(PHYSICAL.test(bad), bad).toBe(true);
    }
    for (const good of ["margin-inline-start: 1px", "inset-inline-end: 0", "text-align: start", "inline-size: 10px", "max-inline-size: 5px"]) {
      expect(PHYSICAL.test(good), good).toBe(false);
    }
  });

  it("app CSS has no physical left/right or width/height", () => {
    for (const f of walk(SRC, [".css"])) {
      const css = readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
      const line = css.split("\n").findIndex((l) => PHYSICAL.test(l));
      expect(line === -1 ? "" : `${f}:${line + 1}: ${css.split("\n")[line]}`).toBe("");
    }
  });
});
