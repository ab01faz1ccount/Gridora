import type { AuthResult, FileRecord, HistoryEntry, Job, Workbook, Workspace } from "@contracts";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export function useWorkspace(id: string) {
  return useQuery({ queryKey: ["workspace", id], queryFn: () => api.get<Workspace>(`/workspaces/${id}`), retry: false });
}

export function useFiles(workspaceId: string) {
  return useQuery({
    queryKey: ["files", workspaceId],
    queryFn: () => api.get<FileRecord[]>(`/workspaces/${workspaceId}/files`),
  });
}

const TERMINAL = new Set(["succeeded", "failed"]);

/** Polls a job with a gentle backoff (0.5 s -> 2 s) until it finishes. */
export function useJob(jobId: string | undefined) {
  return useQuery({
    queryKey: ["job", jobId],
    enabled: Boolean(jobId),
    queryFn: () => api.get<Job>(`/jobs/${jobId}`),
    refetchInterval: (q) =>
      q.state.data && TERMINAL.has(q.state.data.status)
        ? false
        : Math.min(2000, 500 + 250 * q.state.dataUpdateCount),
    retry: false,
  });
}

export function useWorkbook(id: string) {
  return useQuery({ queryKey: ["workbook", id], queryFn: () => api.get<Workbook>(`/workbooks/${id}`), retry: false });
}

export function openFile(fileId: string): Promise<Workbook> {
  return api.post<Workbook>(`/files/${fileId}/open`);
}

export const HISTORY_PAGE = 50;

/** Change history of a document, newest first, a page at a time (the cursor is the last seq seen). */
export function useHistory(id: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: ["history", id],
    enabled,
    retry: false,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      api.get<HistoryEntry[]>(`/documents/${id}/history`, { query: { limit: HISTORY_PAGE, cursor: pageParam } }),
    getNextPageParam: (last) =>
      last.length === HISTORY_PAGE ? String(last[last.length - 1]!.seq) : undefined,
  });
}
