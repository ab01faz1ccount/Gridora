import { useState, type FormEvent } from "react";
import { ApiError } from "@/api/client";
import { errorKey } from "@/api/errors";
import { useChangePassword, useSession } from "@/api/hooks";
import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { useT } from "@/i18n";

export function AccountPage() {
  const t = useT();
  const session = useSession();
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const mismatch = again !== "" && again !== next;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (next !== again) return;
    change.mutate(
      { current_password: current, new_password: next },
      { onSuccess: () => { setCurrent(""); setNext(""); setAgain(""); } },
    );
  }

  let error: string | undefined;
  if (change.error) {
    const e = change.error;
    error = e instanceof ApiError && e.code === "unauthenticated" ? t("account.wrongCurrent") : t(errorKey(e));
  }

  return (
    <section className="content" aria-labelledby="account-title">
      <h1 id="account-title">{t("account.title")}</h1>
      <p>{t("account.signedInAs")} <b dir="ltr">{session.data?.user.username}</b></p>
      <form className="card" onSubmit={onSubmit} aria-labelledby="pw-title">
        <h2 id="pw-title">{t("account.changePassword")}</h2>
        <TextField label={t("account.current")} type="password" value={current} autoComplete="current-password" dir="ltr"
          required onChange={(e) => setCurrent(e.target.value)} />
        <TextField label={t("account.new")} type="password" value={next} autoComplete="new-password" dir="ltr"
          required minLength={10} onChange={(e) => setNext(e.target.value)} />
        <TextField label={t("auth.confirmPassword")} type="password" value={again} autoComplete="new-password" dir="ltr"
          required onChange={(e) => setAgain(e.target.value)} error={mismatch ? t("auth.passwordMismatch") : error} />
        <Button type="submit" variant="primary" disabled={change.isPending || mismatch}>{t("account.save")}</Button>
        {change.isSuccess ? <p role="status">{t("account.saved")}</p> : null}
      </form>
    </section>
  );
}
