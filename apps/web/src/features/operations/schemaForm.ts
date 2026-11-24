// The part of the parameter-form renderer that needs no React: defaults, visibility, ordering and
// cleaning of the submitted value. Vocabulary: packages/dataops/docs/PARAMS_SCHEMA.md.
export type Schema = Record<string, unknown>;
export type Value = unknown;

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

/** Follows a local `$ref` ("#/$defs/Name"); anything else is returned unchanged. */
export function resolve(schema: Schema, root: Schema): Schema {
  let cur = schema;
  for (let i = 0; i < 8; i++) {
    const ref = cur["$ref"];
    if (typeof ref !== "string" || !ref.startsWith("#/$defs/")) return cur;
    const defs = root["$defs"];
    const next = isObj(defs) ? defs[ref.slice("#/$defs/".length)] : undefined;
    if (!isObj(next)) return cur;
    cur = next;
  }
  return cur;
}

export function isNullable(schema: Schema): Schema | null {
  const any = arr(schema["anyOf"]);
  if (any.length !== 2) return null;
  const nonNull = any.filter((b) => !(isObj(b) && b["type"] === "null"));
  return nonNull.length === 1 && isObj(nonNull[0]) ? nonNull[0] : null;
}

export interface Union {
  discriminator: string;
  branches: { value: string; schema: Schema }[];
}

/** A discriminated union: every branch has a `const` property in common (`kind`, `mode`). */
export function unionOf(schema: Schema, root: Schema): Union | null {
  const any = arr(schema["anyOf"]);
  if (any.length < 2 || isNullable(schema)) return null;
  const branches = any.filter(isObj).map((b) => resolve(b, root));
  if (branches.length !== any.length) return null;
  const first = branches[0] ? props(branches[0]) : {};
  for (const name of Object.keys(first)) {
    const vals = branches.map((b) => {
      const p = props(b)[name];
      return isObj(p) && typeof p["const"] === "string" ? p["const"] : null;
    });
    if (vals.every((v): v is string => v !== null)) {
      return { discriminator: name, branches: branches.map((s, i) => ({ value: vals[i] as string, schema: s })) };
    }
  }
  return null;
}

export function props(schema: Schema): Record<string, Schema> {
  const p = schema["properties"];
  if (!isObj(p)) return {};
  const out: Record<string, Schema> = {};
  for (const [k, v] of Object.entries(p)) if (isObj(v)) out[k] = v;
  return out;
}

/** Property names in display order: `x-gridora-order`, then declaration order. */
export function orderedKeys(schema: Schema): string[] {
  const p = props(schema);
  const keys = Object.keys(p);
  const ord = (k: string): number => {
    const o = p[k]?.["x-gridora-order"];
    return typeof o === "number" ? o : Number.MAX_SAFE_INTEGER;
  };
  return keys.map((k, i) => ({ k, i })).sort((a, b) => ord(a.k) - ord(b.k) || a.i - b.i).map((x) => x.k);
}

export function isRequired(schema: Schema, key: string): boolean {
  return arr(schema["required"]).includes(key);
}

/** `x-gridora-visible-if` against the values of the sibling properties. */
export function isVisible(field: Schema, siblings: Record<string, unknown>): boolean {
  const cond = field["x-gridora-visible-if"];
  if (!isObj(cond) || typeof cond["property"] !== "string") return true;
  const actual = siblings[cond["property"]];
  if ("equals" in cond) return actual === cond["equals"];
  if (Array.isArray(cond["in"])) return cond["in"].includes(actual);
  return true;
}

export function isHidden(field: Schema): boolean {
  return field["x-gridora-hidden"] === true;
}

const clone = <T,>(v: T): T => (v === undefined ? v : (JSON.parse(JSON.stringify(v)) as T));

/** Starting value of a field. Required scalars start empty (the server says what is missing). */
export function defaultFor(schemaIn: Schema, root: Schema, depth = 0): Value {
  const schema = resolve(schemaIn, root);
  if ("default" in schema) return clone(schema["default"]);
  if ("const" in schema) return schema["const"];
  const inner = isNullable(schema);
  if (inner) return null;
  const union = unionOf(schema, root);
  if (union?.branches[0]) return defaultFor(union.branches[0].schema, root, depth + 1);
  const en = arr(schema["enum"]);
  if (en.length > 0) return en[0];
  switch (schema["type"]) {
    case "object": {
      if (depth > 6) return {};
      const out: Record<string, unknown> = {};
      for (const [k, s] of Object.entries(props(schema))) {
        const rs = resolve(s, root);
        if (isRequired(schema, k) || "default" in rs || "const" in rs || rs["x-gridora-hidden"] === true) {
          out[k] = defaultFor(s, root, depth + 1);
        }
      }
      return out;
    }
    case "array": {
      const min = typeof schema["minItems"] === "number" ? schema["minItems"] : 0;
      const items = isObj(schema["items"]) ? schema["items"] : null;
      return Array.from({ length: items ? Math.min(min, 1) : 0 }, () => defaultFor(items as Schema, root, depth + 1));
    }
    case "boolean":
      return false;
    case "integer":
    case "number":
      return undefined;
    default:
      return "";
  }
}

/**
 * The value that is sent: fields hidden by `visible-if` are left out, so are empty optional
 * strings, `undefined` and empty optional arrays/objects. Required fields are always kept so the
 * server can say what is missing.
 */
export function cleanValue(schemaIn: Schema, root: Schema, value: Value, required = true): Value {
  const schema = resolve(schemaIn, root);
  const inner = isNullable(schema);
  if (inner) return value === null || value === undefined || value === "" ? null : cleanValue(inner, root, value, true);
  const union = unionOf(schema, root);
  if (union && isObj(value)) {
    const branch = union.branches.find((b) => b.value === value[union.discriminator]) ?? union.branches[0];
    return branch ? cleanValue(branch.schema, root, value, true) : value;
  }
  if (schema["type"] === "object" && isObj(value)) {
    const out: Record<string, unknown> = {};
    for (const k of orderedKeys(schema)) {
      const field = props(schema)[k] as Schema;
      if (!isVisible(resolve(field, root), value) && !isHidden(resolve(field, root))) continue;
      const cleaned = cleanValue(field, root, value[k], isRequired(schema, k));
      if (cleaned !== undefined) out[k] = cleaned;
    }
    return out;
  }
  if (schema["type"] === "array") {
    const items = isObj(schema["items"]) ? schema["items"] : null;
    const list = arr(value).map((v) => (items ? cleanValue(items, root, v, true) : v));
    return list.length === 0 && !required ? undefined : list;
  }
  if (value === undefined) return undefined;
  if (value === "" && !required && !("default" in schema)) return undefined;
  if (typeof value === "number" && Number.isNaN(value)) return undefined;
  return value;
}

/** ValidationError.path is relative to the Operation root; the form works inside `params`. */
export function fieldPath(errorPath: string): string | null {
  return errorPath.startsWith("/params") ? errorPath.slice("/params".length) || "/" : null;
}
