# Operation parameter schemas — vocabulary for form generation

Status: **vocabulary version 1, specification (condition C2.3).** Implemented from M1 on (PR for `sort`, `filter`, `remove_duplicates`), where golden tests pin the generated schemas. Audience: Agent 3 (form renderer), Agent 0 (review). Owner: Agent 2.

`OperationDescriptor.params_schema` is a JSON Schema (draft 2020-12) generated from each operation's pydantic params model, plus the `x-gridora-*` keywords below. The **generated schema is normative** and is pinned by golden files in `tests/golden/` (one per operation, from M1 on); examples in this file are illustrative and may differ in detail.

## 1. Standard JSON Schema subset used

The renderer must understand exactly this subset; anything else must fall back to an "unsupported field" row (shown with the field title/key, value editable as nothing, and the form still submittable if the field is optional).

| Keyword | Use |
|---|---|
| `type` | `string`, `integer`, `number`, `boolean`, `array`, `object`, `null` (only in a nullable `anyOf`) |
| `properties`, `required` | object fields; field order = `x-gridora-order`, else declaration order |
| `additionalProperties: false` | always set on objects (the server rejects unknown fields) |
| `enum`, `const` | choice lists, fixed discriminators |
| `default` | initial form value |
| `minimum`, `maximum`, `minLength`, `maxLength`, `minItems`, `maxItems` | client hints; the server is the authority |
| `items` | arrays (lists of keys, conditions, ...) |
| `anyOf` | only two shapes: nullable value (`[X, {"type":"null"}]`), or a discriminated union where every branch has a `const` discriminator property (`"kind"`, `"mode"`) |
| `$defs` / `$ref` | local references only (`#/$defs/...`), and only for **recursive** structures (e.g. filter condition groups); every other nested model is inlined |
| `title`, `description` | **i18n keys, not display text** (see section 3) |

Not used: `pattern` (server-side only), `format`, `if/then/else`, `dependentRequired`, `patternProperties`, `oneOf`, remote `$ref`. Conditional visibility uses `x-gridora-visible-if`.

## 2. `x-gridora-*` keywords

Unknown `x-gridora-*` keywords must be ignored by the renderer. The root schema carries `"x-gridora-vocab": 1`; a renderer seeing a higher version still renders what it understands.

| Keyword | Value | Meaning |
|---|---|---|
| `x-gridora-vocab` | integer (root only) | vocabulary version |
| `x-gridora-column` | `true` | the string (or array of strings, for array items) is a **column name** of the target table/range; render a column picker |
| `x-gridora-column-of` | `"target"` (default) or `"extra_targets/<i>"` | which input's columns to offer (`join` right-hand keys use `"extra_targets/0"`) |
| `x-gridora-column-types` | array of `"text"`, `"number"`, `"date"`, `"bool"` | restrict the offered columns by logical type |
| `x-gridora-widget` | `"select"`, `"radio"`, `"checkbox"`, `"textarea"`, `"number"`, `"column-list"`, `"sort-keys"`, `"condition-builder"`, `"expression-builder"` | rendering hint; the last three are dedicated builder widgets for recursive structures (conditions, expression trees) that plain JSON Schema cannot express for a form. A renderer without that widget uses the unsupported-field fallback |
| `x-gridora-order` | integer | display order inside an object |
| `x-gridora-group` | i18n key | groups fields under a collapsible heading (e.g. "advanced options") |
| `x-gridora-visible-if` | `{"property": "<sibling>", "equals": <value>}` (or `"in": [...]`) | show the field only when a sibling has the value; hidden fields are omitted from the submitted params |
| `x-gridora-enum-labels` | `{ "<enum value>": "<i18n key>" }` | display labels for `enum` values |
| `x-gridora-unit` | i18n key | unit hint next to numeric fields |
| `x-gridora-persian-option` | `true` | marks options specific to Persian text handling, so the UI may group or highlight them |
| `x-gridora-hidden` | `true` | internal field (the `kind` discriminator of a union branch); never rendered, always submitted with its `const`/default value |

**Tool inputs.** A step parameter can be bound at run time by a `{"$input": "<name>"}` placeholder (`ToolInput.kind` = `column` | `range` | `value`). Allowed positions are derived from the schema: `column` inputs only where `x-gridora-column` is true; `range` inputs only where the schema references the contract `Range` shape; `value` inputs only where the schema type is a scalar (`string`, `integer`, `number`, `boolean`). The form renderer for Tool authoring may offer "bind to a Tool input" on exactly those fields.

## 3. i18n keys

Descriptor and schema texts are keys; the text lives in `gridora_dataops.catalog(locale)` (flat `key -> text`, served by the API at `GET /operations/i18n`). A missing key is rendered as the key itself (never as an empty string).

| What | Key |
|---|---|
| operation label / description | `ops.<type>.label`, `ops.<type>.description` |
| category | `ops.categories.<category>` |
| a parameter's title / description | `ops.<type>.params.<name>.title`, `.description` |
| an enum value label | `ops.<type>.params.<name>.options.<value>` |
| validation message / hint | `errors.<code>.message`, `errors.<code>.hint` (same catalog; `ValidationError.message` carries an English default, the UI may translate by `code`) |

Top-level parameter names are joined with dots (`ops.sort.params.keys.title`). **Fields of a nested model are keyed by the model's name**, not by the path, so every use of the model shares one set of texts: `ops.sort.defs.SortKey.direction.title`, `ops.filter.defs.Condition.op.options.eq`, `ops.filter.defs.Group.logic.title`. Array items of plain values use `<param>.items.title`. Persian text is required for every key; English may be added later but a test fails if a key is missing from `fa`.

## 4. Error paths

`ValidationError.path` is a JSON pointer **relative to the Operation root**, so `/params/keys/0/column` points at the first sort key's column. The form maps a path back to a field by stripping `/params`.

## 5. Illustrative example (`sort`)

```json
{
  "x-gridora-vocab": 1,
  "type": "object",
  "additionalProperties": false,
  "required": ["keys"],
  "properties": {
    "has_header": {"type": "boolean", "default": true,
                   "title": "ops.sort.params.has_header.title", "x-gridora-order": 0},
    "keys": {
      "type": "array", "minItems": 1, "maxItems": 8,
      "title": "ops.sort.params.keys.title", "x-gridora-widget": "sort-keys", "x-gridora-order": 1,
      "items": {
        "type": "object", "additionalProperties": false, "required": ["column"],
        "properties": {
          "column":    {"type": "string", "x-gridora-column": true,
                        "title": "ops.sort.defs.SortKey.column.title"},
          "direction": {"type": "string", "enum": ["asc", "desc"], "default": "asc",
                        "title": "ops.sort.defs.SortKey.direction.title",
                        "x-gridora-enum-labels": {"asc": "ops.sort.defs.SortKey.direction.options.asc",
                                                   "desc": "ops.sort.defs.SortKey.direction.options.desc"}},
          "nulls":     {"type": "string", "enum": ["first", "last"], "default": "last",
                        "title": "ops.sort.defs.SortKey.nulls.title"}
        }
      }
    },
    "collation": {"type": "string", "enum": ["persian", "binary"], "default": "persian",
                  "title": "ops.sort.params.collation.title", "x-gridora-persian-option": true,
                  "x-gridora-group": "ops.groups.advanced"}
  }
}
```

## 6. Recursive structures

`filter` conditions and `computed_column` expressions are trees. Their shape appears in `$defs` (for `filter`: `Condition` / `Group` with a hidden `kind` discriminator, see `tests/golden/filter.schema.json` from M1 on), but the form renderer is expected to use the dedicated `condition-builder` / `expression-builder` widgets. Until Agent 3 provides them, the fallback row ("unsupported field") applies and those two operations can still be run from a saved Tool or via the API.

## 7. Versioning

`Operation.schema_version` versions the **params** of one operation; the vocabulary version above versions this document. Adding an `x-gridora-*` keyword or widget name is backward compatible (older renderers ignore it); renaming or changing the meaning of one bumps `x-gridora-vocab`.
