import type { AuthResult, Workspace } from "@contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, setCsrfToken } from "./client";

export const keys = { me: ["me"] as const, workspaces: ["workspaces"] as const };

/** The current session, or null when signed out (a 401 is a normal answer here, not an error). */
export function useSession() {
  return useQuery({
    queryKey: keys.me,
    queryFn: async (): Promise<AuthResult | null> => {
      try {
        const me = await api.get<AuthResult>("/auth/me");
        setCsrfToken(me.csrf_token);
        return me;
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          setCsrfToken(null);
          return null;
        }
        throw e;
      }
    },
    staleTime: Infinity,
    retry: false,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { username: string; password: string }) =>
      api.post<AuthResult>("/auth/login", v),
    onSuccess: (me) => {
      setCsrfToken(me.csrf_token);
      qc.setQueryData(keys.me, me);
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/auth/logout"),
    onSettled: () => {
      setCsrfToken(null);
      // Update `me` in place so mounted observers see "signed out" (qc.clear() would detach
      // them), then drop everything else so no data of the previous user stays cached.
      qc.setQueryData(keys.me, null);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== keys.me[0] });
    },
  });
}

export function useWorkspaces() {
  return useQuery({ queryKey: keys.workspaces, queryFn: () => api.get<Workspace[]>("/workspaces") });
}

export function useCreateWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.post<Workspace>("/workspaces", { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.workspaces }),
  });
}

export function useRenameWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; name: string }) =>
      api.patch<Workspace>(`/workspaces/${v.id}`, { name: v.name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.workspaces }),
  });
}

export function useDeleteWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    // Destructive: the server refuses without ?confirm=true (the UI asks first).
    mutationFn: (id: string) => api.delete<void>(`/workspaces/${id}`, { query: { confirm: true } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.workspaces }),
  });
}
