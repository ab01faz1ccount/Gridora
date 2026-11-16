import { useEffect } from "react";
import { useSession } from "@/api/hooks";
import { LoginPage } from "@/features/auth/LoginPage";
import { WorkbookPage } from "@/features/workbook/WorkbookPage";
import { WorkspacesPage } from "@/features/workspaces/WorkspacesPage";
import { Toasts } from "@/components/Toasts";
import { applyDocumentLocale, useT } from "@/i18n";
import { usePrefs } from "@/state/prefs";
import { navigate, usePath } from "./router";
import { Shell } from "./Shell";

/** /workbooks/<id> (ids are UUIDs; anything else is not a workbook route). */
export function workbookId(path: string): string | null {
  const m = /^\/workbooks\/([0-9a-fA-F-]{36})$/.exec(path);
  return m?.[1] ?? null;
}

export function App() {
  const t = useT();
  const locale = usePrefs((s) => s.locale);
  const session = useSession();
  const path = usePath();
  const signedIn = Boolean(session.data);

  useEffect(() => applyDocumentLocale(locale), [locale]);

  // Routes: signed out -> /login; signed in -> /workspaces.
  useEffect(() => {
    if (session.isPending) return;
    if (!signedIn && path !== "/login") navigate("/login", true);
    if (signedIn && path !== "/workspaces" && !workbookId(path)) navigate("/workspaces", true);
  }, [session.isPending, signedIn, path]);

  let body;
  if (session.isPending) body = <p className="content">{t("common.loading")}</p>;
  else if (!signedIn) body = <LoginPage />;
  else {
    const wbId = workbookId(path);
    body = <Shell>{wbId ? <WorkbookPage id={wbId} /> : <WorkspacesPage />}</Shell>;
  }

  return (
    <>
      {body}
      <Toasts />
    </>
  );
}
