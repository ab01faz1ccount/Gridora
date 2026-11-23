// Renders an operation's JSON-Schema parameters (vocabulary: packages/dataops/docs/PARAMS_SCHEMA.md).
// Anything it does not understand becomes a labelled "no form for this option" row, never a crash.
import { useId } from "react";
import { Button } from "@/components/Button";
import type { useT } from "@/i18n";
import {
  defaultFor, isHidden, isNullable, isRequired, isVisible, orderedKeys, props, resolve, unionOf,
  type Schema, type Value,
} from "./schemaForm";

type T = ReturnType<typeof useT>;

export interface FormCtx {
  root: Schema;
  /** catalog text of a title/description key; the key itself when missing */
  tr: (key: unknown) => string;
  /** column names offered by `x-gridora-column` fields; empty = a plain text box */
  columns: string[];
  /** messages by path inside `params` ("/keys/0/column") */
  errors: Map<string, string>;
  t: T;
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

interface FieldProps {
  ctx: FormCtx;
  schema: Schema;
  value: Value;
  onChange: (v: Value) => void;
  path: string;
  label: string;
  required?: boolean;
}

function ErrorLine({ id, text }: { id: string; text: string | undefined }) {
  return text ? <p id={id} className="field-error" role="alert">{text}</p> : null;
}

export function Field(p: FieldProps) {
  const { ctx, onChange, path, label } = p;
  const schema = resolve(p.schema, ctx.root);
  const id = useId();
  const errId = `${id}-err`;
  const error = ctx.errors.get(path);
  const describedBy = error ? errId : undefined;

  const nullable = isNullable(schema);
  if (nullable) {
    return <Field {...p} schema={nullable} onChange={(v) => onChange(v === "" ? null : v)} value={p.value ?? ""} />;
  }

  const union = unionOf(schema, ctx.root);
  if (union) {
    const current = isObj(p.value) ? p.value[union.discriminator] : undefined;
    const branch = union.branches.find((b) => b.value === current) ?? union.branches[0];
    return (
      <fieldset className="opf-group">
        <legend>{label}</legend>
        <div className="field">
          <select value={branch?.value ?? ""} aria-label={label} onChange={(e) => {
            const next = union.branches.find((b) => b.value === e.target.value);
            if (next) onChange(defaultFor(next.schema, ctx.root));
          }}>
            {union.branches.map((b) => <option key={b.value} value={b.value}>{ctx.tr(b.schema["title"]) === "" ? b.value : ctx.tr(b.schema["title"])}</option>)}
          </select>
        </div>
        {branch ? <ObjectFields {...p} schema={branch.schema} /> : null}
      </fieldset>
    );
  }

  const en = Array.isArray(schema["enum"]) ? (schema["enum"] as unknown[]) : null;
  if (en) {
    const labels = isObj(schema["x-gridora-enum-labels"]) ? schema["x-gridora-enum-labels"] : {};
    return (
      <div className="field">
        <label htmlFor={id}>{label}</label>
        <select id={id} value={String(p.value ?? "")} aria-invalid={error ? true : undefined} aria-describedby={describedBy}
          onChange={(e) => onChange(en.find((x) => String(x) === e.target.value))}>
          {en.map((x) => <option key={String(x)} value={String(x)}>{ctx.tr(labels[String(x)]) || String(x)}</option>)}
        </select>
        <ErrorLine id={errId} text={error} />
      </div>
    );
  }

  switch (schema["type"]) {
    case "boolean":
      return (
        <div className="field opf-check">
          <label htmlFor={id}>
            <input id={id} type="checkbox" checked={p.value === true} onChange={(e) => onChange(e.target.checked)} />
            {" "}{label}
          </label>
          <ErrorLine id={errId} text={error} />
        </div>
      );
    case "integer":
    case "number":
      return (
        <div className="field">
          <label htmlFor={id}>{label}</label>
          <input id={id} type="number" inputMode="decimal" step={schema["type"] === "integer" ? 1 : "any"}
            min={typeof schema["minimum"] === "number" ? schema["minimum"] : undefined}
            max={typeof schema["maximum"] === "number" ? schema["maximum"] : undefined}
            value={typeof p.value === "number" ? p.value : ""} aria-invalid={error ? true : undefined} aria-describedby={describedBy}
            onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} />
          <ErrorLine id={errId} text={error} />
        </div>
      );
    case "string": {
      const isColumn = schema["x-gridora-column"] === true;
      const ownColumns = !("x-gridora-column-of" in schema) || schema["x-gridora-column-of"] === "target";
      const text = typeof p.value === "string" ? p.value : "";
      if (isColumn && ownColumns && ctx.columns.length > 0) {
        const known = ctx.columns.includes(text) || text === "";
        return (
          <div className="field">
            <label htmlFor={id}>{label}</label>
            <select id={id} value={text} aria-invalid={error ? true : undefined} aria-describedby={describedBy}
              onChange={(e) => onChange(e.target.value)}>
              <option value="">{ctx.t("opPanel.choose")}</option>
              {known ? null : <option value={text}>{text}</option>}
              {ctx.columns.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <ErrorLine id={errId} text={error} />
          </div>
        );
      }
      const multiline = schema["x-gridora-widget"] === "textarea";
      return (
        <div className="field">
          <label htmlFor={id}>{label}</label>
          {multiline ? (
            <textarea id={id} value={text} dir="auto" rows={3} aria-invalid={error ? true : undefined} aria-describedby={describedBy}
              onChange={(e) => onChange(e.target.value)} />
          ) : (
            <input id={id} type="text" value={text} dir="auto" aria-invalid={error ? true : undefined} aria-describedby={describedBy}
              onChange={(e) => onChange(e.target.value)} />
          )}
          <ErrorLine id={errId} text={error} />
        </div>
      );
    }
    case "array":
      return <ArrayField {...p} schema={schema} />;
    case "object":
      return (
        <fieldset className="opf-group">
          <legend>{label}</legend>
          <ObjectFields {...p} schema={schema} />
        </fieldset>
      );
    default:
      return (
        <div className="field">
          <span>{label}</span>
          <p className="muted">{ctx.t("opPanel.unsupportedField")}</p>
        </div>
      );
  }
}

function ArrayField(p: FieldProps) {
  const { ctx, schema, path, onChange } = p;
  const items = isObj(schema["items"]) ? schema["items"] : null;
  const list = Array.isArray(p.value) ? (p.value as Value[]) : [];
  const max = typeof schema["maxItems"] === "number" ? schema["maxItems"] : Infinity;
  const min = typeof schema["minItems"] === "number" ? schema["minItems"] : 0;
  const error = ctx.errors.get(path);
  if (!items) {
    return <div className="field"><span>{p.label}</span><p className="muted">{ctx.t("opPanel.unsupportedField")}</p></div>;
  }
  return (
    <fieldset className="opf-group">
      <legend>{p.label}</legend>
      {list.map((item, i) => (
        <div key={i} className="opf-item">
          <Field ctx={ctx} schema={items} value={item} path={`${path}/${i}`}
            label={ctx.t("opPanel.item", { n: i + 1 })}
            onChange={(v) => onChange(list.map((x, j) => (j === i ? v : x)))} />
          <Button onClick={() => onChange(list.filter((_, j) => j !== i))} disabled={list.length <= min}
            aria-label={ctx.t("opPanel.removeItem")}>{ctx.t("opPanel.removeItem")}</Button>
        </div>
      ))}
      <Button onClick={() => onChange([...list, defaultFor(items, ctx.root)])} disabled={list.length >= max}>
        {ctx.t("opPanel.addItem")}
      </Button>
      {error ? <p className="field-error" role="alert">{error}</p> : null}
    </fieldset>
  );
}

/** The properties of an object schema: ordered, `visible-if` applied, grouped, hidden ones skipped. */
function ObjectFields(p: FieldProps) {
  const { ctx, schema, path, onChange } = p;
  const value = isObj(p.value) ? p.value : {};
  const fields = props(schema);
  const shown = orderedKeys(schema).filter((k) => {
    const f = resolve(fields[k] as Schema, ctx.root);
    return !isHidden(f) && isVisible(f, value);
  });
  const render = (k: string) => {
    const f = fields[k] as Schema;
    const rf = resolve(f, ctx.root);
    return (
      <Field key={k} ctx={ctx} schema={f} value={value[k]} path={`${path}/${k}`}
        label={ctx.tr(rf["title"]) || k} required={isRequired(schema, k)}
        onChange={(v) => onChange({ ...value, [k]: v })} />
    );
  };
  const groupOf = (k: string): string | null => {
    const g = resolve(fields[k] as Schema, ctx.root)["x-gridora-group"];
    return typeof g === "string" ? g : null;
  };
  const plain = shown.filter((k) => groupOf(k) === null);
  const groups = [...new Set(shown.map(groupOf).filter((g): g is string => g !== null))];
  return (
    <>
      {plain.map(render)}
      {groups.map((g) => (
        <details key={g} className="opf-more">
          <summary>{ctx.tr(g) || ctx.t("opPanel.moreOptions")}</summary>
          {shown.filter((k) => groupOf(k) === g).map(render)}
        </details>
      ))}
    </>
  );
}

/** The form of a whole operation: the root schema is an object; hidden fields keep their value. */
export function SchemaForm({ ctx, value, onChange }: { ctx: FormCtx; value: Value; onChange: (v: Value) => void }) {
  return <ObjectFields ctx={ctx} schema={ctx.root} value={value} path="" label="" onChange={onChange} />;
}
