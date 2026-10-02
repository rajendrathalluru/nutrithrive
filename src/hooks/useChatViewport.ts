import { useLayoutEffect, useRef } from 'react';

export const useChatViewport = () => {
  const shellRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const shell = shellRef.current;
    if (!shell) return;

    const root = document.documentElement;
    const alreadyOpen = root.classList.contains('tw-chat-open');
    const viewport = window.visualViewport;
    let frameId: number | undefined;

    const updateViewport = () => {
      frameId = undefined;
      if (viewport && Math.abs(viewport.scale - 1) > 0.01) return;

      const height = viewport?.height ?? window.innerHeight;
      if (height <= 0) return;

      shell.style.setProperty('--tw-viewport-height', `${height}px`);
      shell.style.setProperty('--tw-viewport-top', `${Math.max(0, viewport?.offsetTop ?? 0)}px`);
    };

    const scheduleUpdate = () => {
      if (frameId === undefined) frameId = window.requestAnimationFrame(updateViewport);
    };

    root.classList.add('tw-chat-open');
    updateViewport();
    window.addEventListener('resize', scheduleUpdate);
    viewport?.addEventListener('resize', scheduleUpdate);
    viewport?.addEventListener('scroll', scheduleUpdate);

    return () => {
      if (frameId !== undefined) window.cancelAnimationFrame(frameId);
      window.removeEventListener('resize', scheduleUpdate);
      viewport?.removeEventListener('resize', scheduleUpdate);
      viewport?.removeEventListener('scroll', scheduleUpdate);
      shell.style.removeProperty('--tw-viewport-height');
      shell.style.removeProperty('--tw-viewport-top');
      if (!alreadyOpen) root.classList.remove('tw-chat-open');
    };
  }, []);

  return shellRef;
};
