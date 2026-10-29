import React, { createContext, FormEvent, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { ArrowRight, Eye, EyeOff, Leaf, LockKeyhole } from 'lucide-react';
import { accessService } from '../services/accessService';
import { ACCESS_REQUIRED_EVENT } from '../services/apiClient';
import './AccessGate.css';

const AccessContext = createContext<(() => void) | undefined>(undefined);
export const useAccessLogout = () => useContext(AccessContext);

export default function AccessGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<'checking' | 'locked' | 'ready' | 'unavailable'>('checking');
  const [enabled, setEnabled] = useState(false);
  const [password, setPassword] = useState('');
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pendingLogout, setPendingLogout] = useState(false);
  const revision = useRef(0);
  const invalidateChecks = useCallback(() => ++revision.current, []);

  const checkAccess = useCallback(async (initial = false) => {
    const current = ++revision.current;
    try {
      const status = await accessService.status();
      if (current !== revision.current) return;
      setEnabled(status.enabled);
      setState(status.authenticated ? 'ready' : 'locked');
    } catch {
      if (current === revision.current && initial) setState('unavailable');
    }
  }, []);

  useEffect(() => {
    void checkAccess(true);
    const lock = () => {
      invalidateChecks();
      setPassword('');
      setVisible(false);
      setError('Your access has expired or the password has changed. Please sign in again.');
      setState('locked');
    };
    window.addEventListener(ACCESS_REQUIRED_EVENT, lock);
    return () => {
      invalidateChecks();
      window.removeEventListener(ACCESS_REQUIRED_EVENT, lock);
    };
  }, [checkAccess, invalidateChecks]);

  useEffect(() => {
    if (state !== 'ready' || !enabled) return;
    const check = () => { void checkAccess(); };
    const interval = window.setInterval(check, 60000);
    window.addEventListener('focus', check);
    window.addEventListener('pageshow', check);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener('focus', check);
      window.removeEventListener('pageshow', check);
    };
  }, [state, enabled, checkAccess]);

  const login = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || !password) return;
    setBusy(true);
    setError('');
    const current = invalidateChecks();
    try {
      await accessService.login(password);
      setPassword('');
      setVisible(false);
      const status = await accessService.status();
      if (current !== revision.current) return;
      if (!status.authenticated) throw new Error('Your browser could not keep the access session. Please allow cookies and try again.');
      setEnabled(status.enabled);
      setState('ready');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Unable to sign in. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    invalidateChecks();
    setState('checking');
    setError('');
    setPendingLogout(true);
    try {
      await accessService.logout();
      setPendingLogout(false);
      setState('locked');
    } catch {
      setError('Sign out could not be completed. Check your connection and try again.');
      setState('unavailable');
    }
  };

  if (state === 'ready') {
    return <AccessContext.Provider value={enabled ? () => { void logout(); } : undefined}>{children}</AccessContext.Provider>;
  }

  return (
    <main className="access-page">
      <section className="access-card" aria-labelledby="access-heading">
        <div className="access-brand"><Leaf size={27} aria-hidden="true" /><span>Thrivewell<span>.</span></span></div>
        <div className="access-symbol"><LockKeyhole size={23} strokeWidth={1.5} aria-hidden="true" /></div>
        <p className="access-eyebrow">A little nourishment, together</p>
        <h1 id="access-heading">Welcome to Thrivewell.</h1>
        {state === 'checking' ? <p role="status">Checking your access…</p> : state === 'unavailable' ? <>
          <p role="alert">{error || 'We couldn’t check access right now. Please check your connection and try again.'}</p>
          <button className="access-submit" type="button" onClick={() => {
            if (pendingLogout) { void logout(); return; }
            setState('checking');
            void checkAccess(true);
          }}>{pendingLogout ? 'Retry sign out' : 'Try again'}</button>
        </> : <>
          <p>Enter the access password shared with you to explore recipes and find what works for you.</p>
          <form onSubmit={login}>
            <label htmlFor="access-password">Access password</label>
            <div className="access-input-wrap">
              <input id="access-password" name="password" type={visible ? 'text' : 'password'} value={password}
                onChange={event => setPassword(event.target.value)} autoComplete="current-password" required maxLength={256}
                disabled={busy} aria-invalid={Boolean(error)} aria-describedby={error ? 'access-error' : undefined} />
              <button type="button" className="access-reveal" aria-label={visible ? 'Hide password' : 'Show password'}
                aria-pressed={visible} onClick={() => setVisible(value => !value)}>
                {visible ? <EyeOff size={19} aria-hidden="true" /> : <Eye size={19} aria-hidden="true" />}
              </button>
            </div>
            {error && <p className="access-error" id="access-error" role="alert">{error}</p>}
            <button className="access-submit" type="submit" disabled={busy || !password}>
              {busy ? 'Signing in…' : 'Continue to Thrivewell'}<ArrowRight size={18} aria-hidden="true" />
            </button>
          </form>
          <p className="access-help">Need access? Ask the person who invited you.</p>
        </>}
        <p className="access-footer">Recipe inspiration, not medical advice.</p>
      </section>
    </main>
  );
}
