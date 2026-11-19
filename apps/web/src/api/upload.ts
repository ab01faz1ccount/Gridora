// Multipart upload with progress and cancel. fetch() has no upload progress, so this uses XHR.
import type { ApiErrorEnvelope, ApiSuccess, FileRecord } from "@contracts";
import { ApiError, getCsrfToken } from "./client";

export interface UploadResult {
  file: FileRecord;
  job_id: string;
}

export function uploadFile(
  workspaceId: string,
  file: File,
  onProgress: (loaded: number, total: number) => void,
  signal?: AbortSignal,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1/workspaces/${workspaceId}/files`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Accept", "application/json");
    const csrf = getCsrfToken();
    if (csrf) xhr.setRequestHeader("X-CSRF-Token", csrf);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded, e.total);
    };
    xhr.onerror = () => reject(new ApiError({ code: "network", message: "network error", status: 0 }));
    xhr.onabort = () => reject(new DOMException("aborted", "AbortError"));
    xhr.onload = () => {
      let json: unknown;
      try {
        json = JSON.parse(xhr.responseText);
      } catch {
        reject(new ApiError({ code: "internal_error", message: "unreadable response", status: xhr.status }));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve((json as ApiSuccess<UploadResult>).data);
        return;
      }
      const env = json as Partial<ApiErrorEnvelope> | null;
      reject(
        new ApiError({
          code: env?.error?.code ?? "bad_request",
          message: env?.error?.message ?? "request failed",
          status: xhr.status,
          details: env?.error?.details,
          requestId: env?.error?.request_id,
        }),
      );
    };
    signal?.addEventListener("abort", () => xhr.abort());

    const form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  });
}
