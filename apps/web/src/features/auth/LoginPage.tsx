import { useState, type FormEvent } from "react";
import { ApiError } from "@/api/client";
import { errorKey } from "@/api/errors";
import { useAuthConfig, useLogin, useRegister } from "@/api/hooks";
import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { useT } from "@/i18n";

/** Sign in, or (when the server allows it) create an account; both end in a signed-in session. */
export function LoginPage() {
  const config = useAuthConfig();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const open = config.data?.registration_enabled ?? false;
  return mode === "signup" && open
    ? <SignUpForm minLength={config.data?.password_min_length ?? 10} onSwitch={() => setMode("signin")} />
    : <SignInForm canSignUp={open} onSwitch={() => setMode("signup")} />;
}

function SignInForm({ canSignUp, onSwitch }: { canSignUp: boolean; onSwitch: () => void }) {
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
        {canSignUp ? (
          <p className="auth-switch"><button type="button" className="linkish" onClick={onSwitch}>{t("auth.signupLink")}</button></p>
        ) : null}
      </form>
    </main>
  );
}

function SignUpForm({ minLength, onSwitch }: { minLength: number; onSwitch: () => void }) {
  const t = useT();
  const register = useRegister();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const mismatch = again !== "" && again !== password;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (password !== again) return;
    register.mutate({ username: username.trim(), password });
  }

  let error: string | undefined;
  if (register.error) {
    const e = register.error;
    error = e instanceof ApiError && e.code === "rate_limited" && e.retryAfter
      ? t("auth.rateLimited", { seconds: e.retryAfter })
      : t(errorKey(e));
  }

  return (
    <main className="auth">
      <form className="card" onSubmit={onSubmit} aria-labelledby="signup-title">
        <h1 id="signup-title">{t("auth.signupTitle")}</h1>
        <TextField label={t("auth.username")} value={username} autoComplete="username" autoCapitalize="none"
          spellCheck={false} dir="ltr" required minLength={3} maxLength={64} onChange={(e) => setUsername(e.target.value)} />
        <p className="muted small">{t("auth.usernameHint")}</p>
        <TextField label={t("auth.password")} type="password" value={password} autoComplete="new-password" dir="ltr"
          required minLength={minLength} onChange={(e) => setPassword(e.target.value)} />
        <p className="muted small">{t("auth.passwordHint", { min: minLength })}</p>
        <TextField label={t("auth.confirmPassword")} type="password" value={again} autoComplete="new-password" dir="ltr"
          required onChange={(e) => setAgain(e.target.value)} error={mismatch ? t("auth.passwordMismatch") : error} />
        <Button type="submit" variant="primary" disabled={register.isPending || mismatch}>
          {register.isPending ? t("auth.signupSubmitting") : t("auth.signupSubmit")}
        </Button>
        <p className="auth-switch"><button type="button" className="linkish" onClick={onSwitch}>{t("auth.signinLink")}</button></p>
      </form>
    </main>
  );
}
