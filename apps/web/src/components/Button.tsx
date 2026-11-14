import type { ButtonHTMLAttributes } from "react";

export function Button({
  variant = "secondary",
  type = "button",
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" }) {
  return <button type={type} className={`btn btn-${variant} ${className}`.trim()} {...rest} />;
}
