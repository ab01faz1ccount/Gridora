import type { ReactNode } from "react";
import { useLogout, useSession } from "@/api/hooks";
import { Button } from "@/components/Button";
import { useT } from "@/i18n";
import { usePrefs, type Calendar, type Digits } from "@/state/prefs";
import { useUi } from "@/state/ui";

export function Shell({ children }: { children: ReactNode }) {
  const t = useT();
  const prefs = usePrefs();
  const session = useSession();
  const logout = useLogout();
  const impl = useUi((s) => s.implementation);
  const stub = impl.engine === "stub" || impl.dataops === "stub";

  return (
    <>
      <header className="topbar">
        <span className="brand">{t("app.name")}</span>
        {stub ? (
          <span className="badge" title={t("app.stubBadgeHint")}>
            {t("app.stubBadge")}
          </span>
        ) : null}
        <span className="spacer" />
        <label className="pref">
          {t("nav.digits")}
          <select value={prefs.digits} onChange={(e) => prefs.set({ digits: e.target.value as Digits })}>
            <option value="latin">{t("digits.latin")}</option>
            <option value="persian">{t("digits.persian")}</option>
            <option value="arabic">{t("digits.arabic")}</option>
          </select>
        </label>
        <label className="pref">
          {t("nav.calendar")}
          <select value={prefs.calendar}
            onChange={(e) => prefs.set({ calendar: e.target.value as Calendar })}>
            <option value="gregorian">{t("calendar.gregorian")}</option>
            <option value="jalali">{t("calendar.jalali")}</option>
          </select>
        </label>
        <Button onClick={() => prefs.set({ locale: prefs.locale === "fa" ? "en" : "fa" })}
          aria-label={t("nav.language")}>
          {t("nav.otherLanguage")}
        </Button>
        {session.data ? (
          <>
            <span className="muted" dir="ltr">{session.data.user.username}</span>
            <Button onClick={() => logout.mutate()}>{t("nav.logout")}</Button>
          </>
        ) : null}
      </header>
      <main className="content">{children}</main>
    </>
  );
}
