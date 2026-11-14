import { useState, type FormEvent } from "react";
import { ApiError } from "@/api/client";
import { errorKey } from "@/api/errors";
import { useLogin } from "@/api/hooks";
import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { useT } from "@/i18n";

export function LoginPage() {
  const t = useT();
  const login = useLogin();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    login.mutate({ username: username.trim(), password });
  }

  let error: string | undefined;
  if (login.error) {
    const e = login.error;
    if (e instanceof ApiError && e.code === "unauthenticated") error = t("auth.invalidCredentials");
    else if (e instanceof ApiError && e.code === "rate_limited" && e.retryAfter)
      error = t("auth.rateLimited", { seconds: e.retryAfter });
    else error = t(errorKey(e));
  }

  return (
    <main className="auth">
      <form className="card" onSubmit={onSubmit} aria-labelledby="login-title">
        <h1 id="login-title">{t("auth.title")}</h1>
        <TextField label={t("auth.username")} value={username} autoComplete="username"
          autoCapitalize="none" spellCheck={false} dir="ltr" required
          onChange={(e) => setUsername(e.target.value)} />
        <TextField label={t("auth.password")} type="password" value={password}
          autoComplete="current-password" dir="ltr" required
          onChange={(e) => setPassword(e.target.value)} error={error} />
        <Button type="submit" variant="primary" disabled={login.isPending}>
          {login.isPending ? t("auth.submitting") : t("auth.submit")}
        </Button>
      </form>
    </main>
  );
}
