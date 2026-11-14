import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-explicit-any": "error",
      "no-restricted-globals": ["error", "localStorage"], // go through state/prefs.ts (guarded)
    },
  },
  {
    files: ["src/state/prefs.ts", "src/test/**", "src/**/*.test.{ts,tsx}"],
    rules: { "no-restricted-globals": "off" },
  },
);
