import { vi } from "vitest";

/** Minimal XMLHttpRequest stand-in for the upload code (jsdom's XHR would try the network). */
export class FakeXhr {
  static instances: FakeXhr[] = [];
  method = "";
  url = "";
  headers: Record<string, string> = {};
  withCredentials = false;
  status = 0;
  responseText = "";
  body: FormData | null = null;
  aborted = false;
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeXhr.instances.push(this);
  }
  open(method: string, url: string) { this.method = method; this.url = url; }
  setRequestHeader(k: string, v: string) { this.headers[k] = v; }
  send(body: FormData) { this.body = body; }
  abort() { this.aborted = true; this.onabort?.(); }

  // test helpers
  progress(loaded: number, total: number) { this.upload.onprogress?.({ lengthComputable: true, loaded, total }); }
  respond(status: number, json: unknown) {
    this.status = status;
    this.responseText = JSON.stringify(json);
    this.onload?.();
  }
  respondText(status: number, text: string) { this.status = status; this.responseText = text; this.onload?.(); }
  fail() { this.onerror?.(); }
}

export function installFakeXhr(): void {
  FakeXhr.instances = [];
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
}
export const lastXhr = (): FakeXhr => {
  const x = FakeXhr.instances[FakeXhr.instances.length - 1];
  if (!x) throw new Error("no upload was started");
  return x;
};
