import { ERROR_CODES } from "@contracts";
import type { MessageKey } from "@/i18n";
import { ApiError } from "./client";

const KNOWN = new Set<string>([...ERROR_CODES, "network"]);

/**
 * Engine/operation reasons (ErrorDetail.code) that have their own plain-language message
 * (docs/UX_SPEC.md F1, F4). The more specific message wins over the generic code message.
 */
const REASONS: Record<string, MessageKey> = {
  "xlsx.legacy_xls": "error.reason.legacy_xls",
  "xlsx.encrypted": "error.reason.encrypted",
  "xlsx.encrypted_or_legacy": "error.reason.encrypted_or_legacy",
  "xlsx.strict_ooxml": "error.reason.strict_ooxml",
  "xlsx.macro_enabled_extension": "error.reason.macro_extension",
  too_large_for_history: "error.reason.too_large_for_history",
  "history.full": "error.reason.history_full",
  "history.nothing_to_undo": "error.reason.nothing_to_undo",
  "history.nothing_to_redo": "error.reason.nothing_to_redo",
  "edit.formulas_unsupported": "error.reason.formulas_unsupported",
  "edit.protected_formula_cell": "error.reason.protected_formula_cell",
  "edit.out_of_range": "error.reason.out_of_range",
  "edit.string_too_long": "error.reason.string_too_long",
  "stub.xlsx_unsupported": "error.reason.stub_xlsx",
  "stub.formulas_unsupported": "error.reason.formulas_unsupported",
  "operation.confirm_required": "error.reason.confirm_required",
  "auth.username_invalid": "error.reason.username_invalid",
  "auth.username_taken": "error.reason.username_taken",
  "auth.password_too_short": "error.reason.password_too_short",
  "auth.password_common": "error.reason.password_common",
  "auth.password_too_long": "error.reason.password_too_long",
  "auth.password_unchanged": "error.reason.password_unchanged",
  "auth.registration_disabled": "error.reason.registration_disabled",
  "auth.registration_full": "error.reason.registration_full",
  "quota.workspaces": "error.reason.quota_workspaces",
  "quota.storage": "error.reason.quota_storage",
};

export function reasonOf(e: unknown): string | undefined {
  if (!(e instanceof ApiError)) return undefined;
  return e.details.map((d) => d.code).find((c) => c in REASONS);
}

/** Catalog key for an error. Unknown codes fall back to a generic message, never to raw text. */
export function errorKey(e: unknown): MessageKey {
  const reason = reasonOf(e);
  if (reason) return REASONS[reason] as MessageKey;
  if (e instanceof ApiError && KNOWN.has(e.code)) return `error.${e.code}` as MessageKey;
  return "error.generic";
}

/** True when the message should offer "Convert to Data Table" (docs/UX_SPEC.md F4). */
export function isTooLargeForHistory(e: unknown): boolean {
  return reasonOf(e) === "too_large_for_history";
}
