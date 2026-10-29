import { accessService } from './accessService';
import { ACCESS_REQUIRED_EVENT, apiFetch } from './apiClient';

const originalFetch = global.fetch;
const originalConfig = window.__APP_CONFIG__;
beforeEach(() => { window.__APP_CONFIG__ = { REACT_APP_BACKEND_URL: 'https://thrivewell.test' }; });
afterEach(() => { global.fetch = originalFetch; window.__APP_CONFIG__ = originalConfig; jest.restoreAllMocks(); });

test('login uses credentialed JSON and never puts the password in the URL', async () => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ enabled: true, authenticated: true }) });
  await accessService.login('test-password');
  expect(global.fetch).toHaveBeenCalledWith('https://thrivewell.test/auth/login', expect.objectContaining({
    method: 'POST', credentials: 'include', cache: 'no-store',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: 'test-password' }),
  }));
});

test.each([401, 429, 500])('surfaces a safe message for status %s', async status => {
  global.fetch = jest.fn().mockResolvedValue({ ok: false, status });
  await expect(accessService.login('wrong')).rejects.toThrow();
});

test('an old backend or malformed status response cannot unlock the app', async () => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'healthy' }) });
  await expect(accessService.status()).rejects.toThrow('Unable to check access');
});

test('protected requests include the cookie and notify the UI on expiration', async () => {
  const dispatch = jest.spyOn(window, 'dispatchEvent');
  global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401 });
  await apiFetch('/ask', { method: 'POST' });
  expect(global.fetch).toHaveBeenCalledWith('/ask', { method: 'POST', credentials: 'include' });
  expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ type: ACCESS_REQUIRED_EVENT }));
});
