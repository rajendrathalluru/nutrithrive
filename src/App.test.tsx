import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import App from './App';

jest.mock('./components/LandingPage', () => function MockLandingPage({ onGetStarted }: { onGetStarted: () => void }) {
  return <button onClick={onGetStarted}>Get Started</button>;
});

jest.mock('./components/NutriThriveChatbot', () => function MockChatbot({ onBackToHome }: { onBackToHome: () => void }) {
  return <main aria-label="Recipe chat"><button onClick={onBackToHome}>Back to Home</button></main>;
});

beforeEach(() => {
  window.history.replaceState(null, '', '/');
});

afterEach(() => {
  jest.restoreAllMocks();
  window.history.replaceState(null, '', '/');
});

test('opens the landing page at the root URL', () => {
  render(<App />);
  expect(screen.getByRole('button', { name: 'Get Started' })).toBeInTheDocument();
  expect(screen.queryByRole('main', { name: 'Recipe chat' })).not.toBeInTheDocument();
});

test.each(['/chat', '/chat/', '/chat?from=bookmark'])('opens the chat directly at %s', path => {
  window.history.replaceState(null, '', path);
  render(<App />);
  expect(screen.getByRole('main', { name: 'Recipe chat' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Get Started' })).not.toBeInTheDocument();
});

test('Get Started updates the URL and a fresh app mount stays on the chat page', () => {
  const pushState = jest.spyOn(window.history, 'pushState');
  const { unmount } = render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Get Started' }));
  expect(pushState).toHaveBeenCalledWith(null, '', '/chat');
  expect(window.location.pathname).toBe('/chat');
  expect(screen.getByRole('main', { name: 'Recipe chat' })).toBeInTheDocument();
  unmount();
  render(<App />);
  expect(screen.getByRole('main', { name: 'Recipe chat' })).toBeInTheDocument();
  expect(pushState).toHaveBeenCalledTimes(1);
});

test('Back to Home updates the URL and a fresh app mount stays on the homepage', () => {
  window.history.replaceState(null, '', '/chat');
  const { unmount } = render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Back to Home' }));
  expect(window.location.pathname).toBe('/');
  expect(screen.getByRole('button', { name: 'Get Started' })).toBeInTheDocument();
  unmount();
  render(<App />);
  expect(screen.getByRole('button', { name: 'Get Started' })).toBeInTheDocument();
});

test('browser Back and Forward synchronize the view and preserve landing anchors', async () => {
  window.history.replaceState(null, '', '/#features');
  render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Get Started' }));
  await act(async () => {
    await new Promise<void>(resolve => {
      window.addEventListener('popstate', () => resolve(), { once: true });
      window.history.back();
    });
  });
  expect(window.location.pathname).toBe('/');
  expect(window.location.hash).toBe('#features');
  expect(screen.getByRole('button', { name: 'Get Started' })).toBeInTheDocument();
  await act(async () => {
    await new Promise<void>(resolve => {
      window.addEventListener('popstate', () => resolve(), { once: true });
      window.history.forward();
    });
  });
  expect(window.location.pathname).toBe('/chat');
  expect(screen.getByRole('main', { name: 'Recipe chat' })).toBeInTheDocument();
});

test('does not treat unrelated paths as the chat route', () => {
  window.history.replaceState(null, '', '/chat-other');
  render(<App />);
  expect(screen.getByRole('button', { name: 'Get Started' })).toBeInTheDocument();
});

test('removes the navigation listener on unmount', () => {
  const removeListener = jest.spyOn(window, 'removeEventListener');
  const { unmount } = render(<App />);
  unmount();
  expect(removeListener).toHaveBeenCalledWith('popstate', expect.any(Function));
});
