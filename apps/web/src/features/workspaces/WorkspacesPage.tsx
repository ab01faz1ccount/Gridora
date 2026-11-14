import type { Workspace } from "@contracts";
import { useState, type FormEvent } from "react";
import { errorKey } from "@/api/errors";
import {
  useCreateWorkspace,
  useDeleteWorkspace,
  useRenameWorkspace,
  useWorkspaces,
} from "@/api/hooks";
import { Button } from "@/components/Button";
import { Dialog } from "@/components/Dialog";
import { TextField } from "@/components/TextField";
import { useT } from "@/i18n";
import { formatDate } from "@/i18n/format";
import { usePrefs } from "@/state/prefs";
import { useUi } from "@/state/ui";

export function WorkspacesPage() {
  const t = useT();
  const { locale, digits, calendar } = usePrefs();
  const push = useUi((s) => s.pushToast);
  const list = useWorkspaces();
  const create = useCreateWorkspace();
  const rename = useRenameWorkspace();
  const del = useDeleteWorkspace();
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<Workspace | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleting, setDeleting] = useState<Workspace | null>(null);

  function fail(e: unknown) {
    push("error", t(errorKey(e)));
  }

  function onCreate(e: FormEvent) {
    e.preventDefault();
    const n = name.trim();
    if (!n) return;
    create.mutate(n, { onSuccess: () => setName(""), onError: fail });
  }

  function onRename(e: FormEvent) {
    e.preventDefault();
    const n = renameValue.trim();
    if (!renaming || !n) return;
    rename.mutate(
      { id: renaming.id, name: n },
      { onSuccess: () => setRenaming(null), onError: fail },
    );
  }

  return (
    <section aria-labelledby="ws-title">
      <h1 id="ws-title">{t("workspaces.title")}</h1>

      <form className="inline-form" onSubmit={onCreate}>
        <TextField label={t("workspaces.nameLabel")} value={name} maxLength={120}
          onChange={(e) => setName(e.target.value)} />
        <Button type="submit" variant="primary" disabled={create.isPending || !name.trim()}>
          {t("workspaces.create")}
        </Button>
      </form>

      {list.isPending ? <p>{t("common.loading")}</p> : null}
      {list.isError ? (
        <p role="alert">
          {t(errorKey(list.error))}{" "}
          <Button onClick={() => void list.refetch()}>{t("common.retry")}</Button>
        </p>
      ) : null}
      {list.data && list.data.length === 0 ? <p className="muted">{t("workspaces.empty")}</p> : null}
      {list.data && list.data.length > 0 ? (
        <ul className="ws-list" aria-label={t("workspaces.listLabel")}>
          {list.data.map((w) => (
            <li key={w.id} className="card ws-item">
              <div>
                <strong>
                  <bdi>{w.name}</bdi>
                </strong>
                <div className="muted">
                  {t("workspaces.createdAt", {
                    date: formatDate(w.created_at, { calendar, digits, locale }),
                  })}
                </div>
              </div>
              <div className="actions">
                <Button onClick={() => { setRenaming(w); setRenameValue(w.name); }}>
                  {t("workspaces.rename")}
                </Button>
                <Button variant="danger" onClick={() => setDeleting(w)}>
                  {t("workspaces.delete")}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      {renaming ? (
        <Dialog title={t("workspaces.renameTitle")} onClose={() => setRenaming(null)}>
          <form onSubmit={onRename}>
            <TextField label={t("workspaces.nameLabel")} value={renameValue} maxLength={120}
              onChange={(e) => setRenameValue(e.target.value)} />
            <div className="dialog-actions">
              <Button onClick={() => setRenaming(null)}>{t("common.cancel")}</Button>
              <Button type="submit" variant="primary" disabled={rename.isPending || !renameValue.trim()}>
                {t("common.save")}
              </Button>
            </div>
          </form>
        </Dialog>
      ) : null}

      {deleting ? (
        <Dialog title={t("workspaces.deleteTitle")} onClose={() => setDeleting(null)}>
          <p>{t("workspaces.deleteBody", { name: deleting.name })}</p>
          <div className="dialog-actions">
            <Button onClick={() => setDeleting(null)}>{t("common.cancel")}</Button>
            <Button variant="danger" disabled={del.isPending}
              onClick={() => del.mutate(deleting.id, { onSuccess: () => setDeleting(null), onError: fail })}>
              {t("workspaces.deleteAction")}
            </Button>
          </div>
        </Dialog>
      ) : null}
    </section>
  );
}
