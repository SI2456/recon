import type { Role } from "./roles";

// Exported so callers that build URLs the browser fetches directly (iframe
// sources, download links) resolve against the same origin as apiRequest.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:4000";

type ApiOptions = RequestInit & {
  auth?: boolean;
};

export async function apiRequest<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", headers.get("Content-Type") || "application/json");
  }

  if (options.auth !== false) {
    const token = localStorage.getItem("reconai_token");
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = payload.detail || payload.error || "Request failed.";
    if (response.status === 401 || String(message).toLowerCase().includes("token")) {
      localStorage.removeItem("reconai_token");
      localStorage.removeItem("reconai_user");
      window.dispatchEvent(new Event("reconai-auth-expired"));
      throw new Error("Session expired. Please sign in again.");
    }
    throw new Error(message);
  }

  return payload as T;
}

export type AuthUser = {
  id: number;
  name: string;
  email: string;
  role: Role;
  firmName?: string;
  gstin?: string;
  icaiNumber?: string;
};

export type AuthResponse = {
  token: string;
  user: AuthUser;
};
