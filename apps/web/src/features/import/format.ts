import { formatNumber } from "@/i18n/format";
import type { Digits } from "@/state/prefs";

/** File size like "12.4 MB" with the user's digit set (KB/MB are conventional in both languages). */
export function formatSize(bytes: number, digits: Digits): string {
  const units = ["B", "KB", "MB", "GB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${formatNumber(Math.round(v * 10) / 10, digits, 1)} ${units[i]}`;
}
