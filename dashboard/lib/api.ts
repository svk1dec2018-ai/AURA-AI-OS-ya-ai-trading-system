export class ApiError extends Error {
  status: number;
  url: string;
  payload: any;

  constructor(message: string, status: number, url: string, payload: any) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.url = url;
    this.payload = payload;
  }
}

async function parseResponse(response: Response, url: string) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.ok === false) {
    const detail = data?.error || data?.detail || "Request failed";
    throw new ApiError(url + " → " + response.status + ": " + detail, response.status, url, data);
  }
  return data;
}

export async function getJson<T = any>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  return (await parseResponse(response, url)) as T;
}

export async function tryGetJson<T = any>(
  url: string
): Promise<{ ok: true; data: T } | { ok: false; error: string; status?: number }> {
  try {
    return { ok: true, data: await getJson<T>(url) };
  } catch (exc) {
    const error = exc instanceof Error ? exc.message : String(exc);
    const status = exc instanceof ApiError ? exc.status : undefined;
    return { ok: false, error, status };
  }
}

export async function postJson<T = any>(url: string, body: unknown): Promise<T> {
  const token = typeof window !== "undefined" ? sessionStorage.getItem("aura-owner-token") : "";
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = "Bearer " + token;
  const response = await fetch(url, { method: "POST", headers, body: JSON.stringify(body) });
  return (await parseResponse(response, url)) as T;
}
