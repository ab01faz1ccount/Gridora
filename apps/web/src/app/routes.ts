const UUID = "[0-9a-fA-F-]{36}";

export type Route =
  | { name: "login" }
  | { name: "workspaces" }
  | { name: "workspace"; id: string }
  | { name: "workbook"; id: string };

export function parseRoute(path: string): Route {
  const ws = new RegExp(`^/workspaces/(${UUID})$`).exec(path);
  if (ws?.[1]) return { name: "workspace", id: ws[1] };
  const wb = new RegExp(`^/workbooks/(${UUID})$`).exec(path);
  if (wb?.[1]) return { name: "workbook", id: wb[1] };
  if (path === "/login") return { name: "login" };
  return { name: "workspaces" };
}

export const isKnownSignedInPath = (path: string): boolean =>
  path === "/workspaces" || /^\/workspaces\/[0-9a-fA-F-]{36}$/.test(path) || /^\/workbooks\/[0-9a-fA-F-]{36}$/.test(path);
