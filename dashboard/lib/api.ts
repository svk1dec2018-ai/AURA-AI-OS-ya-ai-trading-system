export async function getJson<T = any>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.ok === false) {
    throw new Error(data?.error || "Request failed: " + response.status);
  }
  return data as T;
}

export async function postJson<T = any>(url: string, body: unknown): Promise<T> {
  const token = typeof window !== "undefined" ? sessionStorage.getItem("aura-owner-token") : "";
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = "Bearer " + token;
  const response = await fetch(url, { method: "POST", headers, body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.ok === false) {
    throw new Error(data?.error || "Request failed: " + response.status);
  }
  return data as T;
}
