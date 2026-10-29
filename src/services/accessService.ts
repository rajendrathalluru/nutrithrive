import { getBackendBaseUrl } from './apiClient';

export interface AccessStatus {
  enabled: boolean;
  authenticated: boolean;
}

async function accessRequest(path: string, options: RequestInit = {}): Promise<AccessStatus> {
  const response = await fetch(`${getBackendBaseUrl()}/auth/${path}`, {
    ...options, credentials: 'include', cache: 'no-store',
  });
  if (!response.ok) {
    if (response.status === 401) throw new Error('That password isn’t correct. Please try again.');
    if (response.status === 429) throw new Error('Too many attempts. Please wait 15 minutes before trying again.');
    throw new Error('Unable to check access right now. Please try again.');
  }
  const data = await response.json();
  if (typeof data.authenticated !== 'boolean' || (path !== 'logout' && typeof data.enabled !== 'boolean')) {
    throw new Error('Unable to check access right now. Please try again.');
  }
  return data;
}

export const accessService = {
  status: () => accessRequest('status'),
  login: (password: string) => accessRequest('login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }),
  }),
  logout: () => accessRequest('logout', { method: 'POST' }),
};
