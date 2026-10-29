export const ACCESS_REQUIRED_EVENT = 'thrivewell:access-required';

export function getBackendBaseUrl(): string {
  const configuredUrl = window.__APP_CONFIG__?.REACT_APP_BACKEND_URL?.trim()
    || process.env.REACT_APP_BACKEND_URL?.trim();
  return (configuredUrl || window.location.origin).replace(/\/+$/, '');
}

export async function apiFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const response = await fetch(url, { ...options, credentials: 'include' });
  if (response.status === 401) window.dispatchEvent(new Event(ACCESS_REQUIRED_EVENT));
  return response;
}
