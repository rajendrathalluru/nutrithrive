import React from 'react';
import { act, render, screen } from '@testing-library/react';
import { useChatViewport } from './useChatViewport';

const ViewportHarness = () => <div ref={useChatViewport()} data-testid="chat-shell" />;
const originalViewport = Object.getOwnPropertyDescriptor(window, 'visualViewport');
const originalHeight = window.innerHeight;
let viewport: EventTarget & { height: number; offsetTop: number; scale: number };
let pendingFrame: FrameRequestCallback | undefined;

beforeEach(() => {
  viewport = Object.assign(new EventTarget(), { height: 720, offsetTop: 0, scale: 1 });
  Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport });
  pendingFrame = undefined;
  jest.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => {
    pendingFrame = callback;
    return 1;
  });
  jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => { pendingFrame = undefined; });
});

afterEach(() => {
  jest.restoreAllMocks();
  if (originalViewport) Object.defineProperty(window, 'visualViewport', originalViewport);
  else Reflect.deleteProperty(window, 'visualViewport');
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalHeight });
  document.documentElement.classList.remove('tw-chat-open');
});

const flushViewport = () => {
  const callback = pendingFrame;
  pendingFrame = undefined;
  act(() => { callback?.(16); });
};

test('fits the visible viewport when browser chrome or the keyboard changes height', () => {
  render(<ViewportHarness />);
  const shell = screen.getByTestId('chat-shell');
  expect(document.documentElement).toHaveClass('tw-chat-open');
  expect(shell.style.getPropertyValue('--tw-viewport-height')).toBe('720px');

  viewport.height = 390;
  viewport.offsetTop = 35;
  viewport.dispatchEvent(new Event('resize'));
  viewport.dispatchEvent(new Event('scroll'));
  expect(window.requestAnimationFrame).toHaveBeenCalledTimes(1);
  flushViewport();
  expect(shell.style.getPropertyValue('--tw-viewport-height')).toBe('390px');
  expect(shell.style.getPropertyValue('--tw-viewport-top')).toBe('35px');

  viewport.height = 760;
  viewport.offsetTop = 0;
  viewport.dispatchEvent(new Event('resize'));
  flushViewport();
  expect(shell.style.getPropertyValue('--tw-viewport-height')).toBe('760px');
  expect(shell.style.getPropertyValue('--tw-viewport-top')).toBe('0px');
});

test('does not reflow the layout during pinch zoom', () => {
  render(<ViewportHarness />);
  viewport.height = 360;
  viewport.scale = 2;
  viewport.dispatchEvent(new Event('resize'));
  flushViewport();
  expect(screen.getByTestId('chat-shell').style.getPropertyValue('--tw-viewport-height')).toBe('720px');
  viewport.height = 680;
  viewport.scale = 1;
  viewport.dispatchEvent(new Event('resize'));
  flushViewport();
  expect(screen.getByTestId('chat-shell').style.getPropertyValue('--tw-viewport-height')).toBe('680px');
});

test('falls back to window height when VisualViewport is unavailable', () => {
  Object.defineProperty(window, 'visualViewport', { configurable: true, value: undefined });
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: 640 });
  render(<ViewportHarness />);
  expect(screen.getByTestId('chat-shell').style.getPropertyValue('--tw-viewport-height')).toBe('640px');
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: 360 });
  window.dispatchEvent(new Event('resize'));
  flushViewport();
  expect(screen.getByTestId('chat-shell').style.getPropertyValue('--tw-viewport-height')).toBe('360px');
});

test('releases page scrolling, listeners, and pending work when leaving the chat', () => {
  const removeViewportListener = jest.spyOn(viewport, 'removeEventListener');
  const removeWindowListener = jest.spyOn(window, 'removeEventListener');
  const { unmount } = render(<ViewportHarness />);
  const shell = screen.getByTestId('chat-shell');
  viewport.dispatchEvent(new Event('resize'));
  unmount();
  expect(document.documentElement).not.toHaveClass('tw-chat-open');
  expect(removeViewportListener).toHaveBeenCalledWith('resize', expect.any(Function));
  expect(removeViewportListener).toHaveBeenCalledWith('scroll', expect.any(Function));
  expect(removeWindowListener).toHaveBeenCalledWith('resize', expect.any(Function));
  expect(window.cancelAnimationFrame).toHaveBeenCalledWith(1);
  expect(shell.style.getPropertyValue('--tw-viewport-height')).toBe('');
  expect(pendingFrame).toBeUndefined();
});

test('ignores a transient zero-sized viewport', () => {
  render(<ViewportHarness />);
  viewport.height = 0;
  viewport.dispatchEvent(new Event('resize'));
  flushViewport();
  expect(screen.getByTestId('chat-shell').style.getPropertyValue('--tw-viewport-height')).toBe('720px');
});
