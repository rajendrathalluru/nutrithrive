import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import AccessGate, { useAccessLogout } from './AccessGate';
import { accessService } from '../services/accessService';
import { ACCESS_REQUIRED_EVENT } from '../services/apiClient';

jest.mock('../services/accessService');
const status = accessService.status as jest.Mock;
const login = accessService.login as jest.Mock;
const logout = accessService.logout as jest.Mock;

function PrivateApp() {
  const signOut = useAccessLogout();
  return <main aria-label="Private application">Recipes{signOut && <button onClick={signOut}>Sign out</button>}</main>;
}

beforeEach(() => {
  jest.resetAllMocks();
  status.mockResolvedValue({ enabled: true, authenticated: false });
  login.mockResolvedValue({ enabled: true, authenticated: true });
  logout.mockResolvedValue({ authenticated: false });
});

afterEach(() => jest.useRealTimers());

const renderGate = () => render(<AccessGate><PrivateApp /></AccessGate>);
const submit = (password = 'a-test-password') => {
  fireEvent.change(screen.getByLabelText('Access password'), { target: { value: password } });
  fireEvent.click(screen.getByRole('button', { name: 'Continue to Thrivewell' }));
};

test('does not mount the application before access is confirmed', async () => {
  renderGate();
  expect(screen.getByRole('status')).toHaveTextContent('Checking your access');
  expect(screen.queryByRole('main', { name: 'Private application' })).not.toBeInTheDocument();
  await screen.findByLabelText('Access password');
  expect(screen.queryByText('Recipes')).not.toBeInTheDocument();
});

test.each([false, true])('allows an authenticated session on refresh (gate enabled: %s)', async enabled => {
  status.mockResolvedValue({ enabled, authenticated: true });
  const { unmount } = renderGate();
  await screen.findByRole('main', { name: 'Private application' });
  expect(Boolean(screen.queryByRole('button', { name: 'Sign out' }))).toBe(enabled);
  unmount();
  renderGate();
  await screen.findByRole('main', { name: 'Private application' });
});

test('supports password visibility, then signs in without storing the password in browser storage', async () => {
  const storage = jest.spyOn(Storage.prototype, 'setItem');
  renderGate();
  const input = await screen.findByLabelText('Access password');
  expect(input).toHaveAttribute('type', 'password');
  fireEvent.click(screen.getByRole('button', { name: 'Show password' }));
  expect(input).toHaveAttribute('type', 'text');
  status.mockResolvedValue({ enabled: true, authenticated: true });
  submit();
  await screen.findByRole('main', { name: 'Private application' });
  expect(login).toHaveBeenCalledWith('a-test-password');
  expect(storage).not.toHaveBeenCalled();
  storage.mockRestore();
});

test.each(['That password isn’t correct. Please try again.', 'Too many attempts. Please wait 15 minutes before trying again.'])('keeps the app locked after login rejection: %s', async message => {
  login.mockRejectedValue(new Error(message));
  renderGate();
  await screen.findByLabelText('Access password');
  submit();
  expect(await screen.findByRole('alert')).toHaveTextContent(message);
  expect(screen.queryByText('Recipes')).not.toBeInTheDocument();
});

test('fails closed when access checking is unavailable, with a working retry', async () => {
  status.mockRejectedValueOnce(new Error('offline'));
  renderGate();
  await screen.findByRole('alert');
  expect(screen.queryByText('Recipes')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  await screen.findByLabelText('Access password');
});

test('checks that the cookie actually works before unlocking', async () => {
  renderGate();
  await screen.findByLabelText('Access password');
  submit();
  expect(await screen.findByRole('alert')).toHaveTextContent('allow cookies');
  expect(screen.queryByText('Recipes')).not.toBeInTheDocument();
});

test('unauthorized API responses lock the app and clear its in-memory view', async () => {
  status.mockResolvedValue({ enabled: true, authenticated: true });
  renderGate();
  await screen.findByText('Recipes');
  act(() => window.dispatchEvent(new Event(ACCESS_REQUIRED_EVENT)));
  await screen.findByLabelText('Access password');
  expect(screen.queryByText('Recipes')).not.toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('password has changed');
});

test('background checks detect expiration and password rotation', async () => {
  jest.useFakeTimers();
  status.mockResolvedValue({ enabled: true, authenticated: true });
  renderGate();
  await screen.findByText('Recipes');
  status.mockResolvedValue({ enabled: true, authenticated: false });
  await act(async () => { jest.advanceTimersByTime(60000); });
  expect(screen.getByLabelText('Access password')).toBeInTheDocument();
});

test('a stale access check cannot reopen the app after an unauthorized API response', async () => {
  let complete: (value: { enabled: boolean; authenticated: boolean }) => void = () => {};
  status.mockImplementation(() => new Promise(resolve => { complete = resolve; }));
  renderGate();
  act(() => window.dispatchEvent(new Event(ACCESS_REQUIRED_EVENT)));
  await act(async () => complete({ enabled: true, authenticated: true }));
  expect(screen.getByLabelText('Access password')).toBeInTheDocument();
});

test('sign out clears the private view and failed sign out can be retried', async () => {
  status.mockResolvedValue({ enabled: true, authenticated: true });
  logout.mockRejectedValueOnce(new Error('offline'));
  renderGate();
  fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Sign out could not be completed');
  expect(screen.queryByText('Recipes')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Retry sign out' }));
  await screen.findByLabelText('Access password');
  await waitFor(() => expect(logout).toHaveBeenCalledTimes(2));
});
