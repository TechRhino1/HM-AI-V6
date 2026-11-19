// Thin fetch wrapper. Auth is the server's HttpOnly session cookie (localhost is auto-admin),
// so there is no token handling here; a 401 tells the app shell to show the login screen.

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

/** The action reached the broker but its outcome is unknown (status UNKNOWN). */
export class UnconfirmedError extends Error {
  constructor(message: string, public body?: unknown) {
    super(message);
  }
}

type Listener = () => void;
const unauthorizedListeners = new Set<Listener>();
export const onUnauthorized = (fn: Listener) => {
  unauthorizedListeners.add(fn);
  return () => {
    unauthorizedListeners.delete(fn);
  };
};

async function request<T>(method: "GET" | "POST", path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });
  const text = await res.text();
  let data: any = undefined;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    data = text;
  }
  if (res.status === 401 && !path.startsWith("/api/auth/")) unauthorizedListeners.forEach((l) => l());
  if (!res.ok) {
    const msg = (data && typeof data === "object" && (data.error || data.message)) || `${res.status} ${res.statusText}`;
    throw new ApiError(res.status, String(msg), data);
  }
  // The broker answers UNKNOWN when it timed out: the order may or may not exist. That is neither
  // success nor refusal (a "failed" retry could double a position), so it gets its own error type.
  if (data && typeof data === "object" && typeof data.status === "string" && /^UNKNOWN$/i.test(data.status)) {
    throw new UnconfirmedError(String(data.reason || data.error || "The broker did not confirm the outcome"), data);
  }
  // Several action endpoints answer 200 with {status: "FAILED" | "ERROR" | "REJECTED", error}.
  if (data && typeof data === "object" && typeof data.status === "string" && /^(FAILED|ERROR|REJECTED|DENIED|BLOCKED)$/i.test(data.status)) {
    throw new ApiError(res.status, String(data.error || data.message || data.reason || data.status), data);
  }
  return data as T;
}

export const api = {
  get: <T,>(path: string, signal?: AbortSignal) => request<T>("GET", path, undefined, signal),
  post: <T,>(path: string, body: unknown = {}) => request<T>("POST", path, body),
};

export const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};
