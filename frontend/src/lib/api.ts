// API 클라이언트: 접근 토큰은 메모리, 갱신 토큰은 localStorage. 401 시 1회 자동 갱신.
const RKEY = "gat.refresh";
let access = "";
let refreshing: Promise<boolean> | null = null;
let onSession: ((user: any | null) => void) | null = null;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

export function setSessionListener(fn: (user: any | null) => void) { onSession = fn; }
export function hasRefresh() { return !!localStorage.getItem(RKEY); }
export function storeSession(data: { access_token: string; refresh_token: string; user: any }) {
  access = data.access_token;
  localStorage.setItem(RKEY, data.refresh_token);
  onSession?.(data.user);
}
export function clearSession() { access = ""; localStorage.removeItem(RKEY); onSession?.(null); }
export function setRefreshToken(token: string) { localStorage.setItem(RKEY, token); }

export async function refresh(): Promise<boolean> {
  const token = localStorage.getItem(RKEY);
  if (!token) return false;
  if (!refreshing) {
    refreshing = fetch("/api/auth/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: token }) })
      .then(async (res) => {
        if (res.status === 401) { clearSession(); return false; } // 만료·폐기된 세션만 로그아웃 처리
        if (!res.ok) return false; // 일시 오류(429·5xx)는 세션을 유지한다
        storeSession(await res.json());
        return true;
      })
      .catch(() => false)
      .finally(() => { refreshing = null; });
  }
  return refreshing;
}

async function parseError(res: Response): Promise<ApiError> {
  let message = `요청 실패 (${res.status})`;
  try {
    const data = await res.json();
    if (typeof data.detail === "string") message = data.detail;
    else if (Array.isArray(data.detail)) message = data.detail.map((d: any) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join(", ");
  } catch { /* 본문 없음 */ }
  return new ApiError(res.status, message);
}

export async function api<T = any>(path: string, opts: { method?: string; body?: any; form?: FormData; headers?: Record<string, string>; raw?: boolean } = {}, retried = false): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers || {}) };
  if (access) headers.Authorization = `Bearer ${access}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
  const res = await fetch(`/api${path}`, { method: opts.method || (body ? "POST" : "GET"), headers, body });
  if (res.status === 401 && !retried && !path.startsWith("/auth/") && (await refresh())) return api(path, opts, true);
  if (!res.ok) throw await parseError(res);
  if (opts.raw) return res as any;
  return (res.headers.get("content-type") || "").includes("json") ? res.json() : (res.text() as any);
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, body?: any, headers?: Record<string, string>) => api<T>(p, { method: "POST", body: body ?? {}, headers });
export const put = <T = any>(p: string, body: any) => api<T>(p, { method: "PUT", body });
export const patch = <T = any>(p: string, body: any) => api<T>(p, { method: "PATCH", body });
export const del = <T = any>(p: string) => api<T>(p, { method: "DELETE" });

export async function download(path: string, filename: string) {
  const res: Response = await api(path, { raw: true });
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

// 업로드 진행률 표시용(XHR). 실패 시 호출 측에서 재시도한다.
export function upload<T = any>(path: string, form: FormData, onProgress: (pct: number) => void): Promise<T> {
  const send = (retried: boolean): Promise<T> => new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${path}`);
    if (access) xhr.setRequestHeader("Authorization", `Bearer ${access}`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100)); };
    xhr.onerror = () => reject(new ApiError(0, "네트워크 오류로 업로드에 실패했습니다"));
    xhr.onload = async () => {
      if (xhr.status === 401 && !retried && (await refresh())) return send(true).then(resolve, reject);
      let data: any = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* noop */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new ApiError(xhr.status, typeof data.detail === "string" ? data.detail : `업로드 실패 (${xhr.status})`));
    };
    xhr.send(form);
  });
  return send(false);
}
