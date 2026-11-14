import { useId, type InputHTMLAttributes } from "react";

export function TextField({
  label,
  error,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }) {
  const id = useId();
  const errId = `${id}-err`;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} aria-invalid={error ? true : undefined}
        aria-describedby={error ? errId : undefined} {...rest} />
      {error ? (
        <p id={errId} className="field-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
