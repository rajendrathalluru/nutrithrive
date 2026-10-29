import React, { useEffect, useState } from 'react';
import './App.css';
import LandingPage from './components/LandingPage';
import NutriThriveChatbot from './components/NutriThriveChatbot';
import { useAccessLogout } from './components/AccessGate';

const getCurrentView = (): 'landing' | 'chatbot' =>
  window.location.pathname.replace(/\/+$/, '') === '/chat' ? 'chatbot' : 'landing';

function App() {
  const onLogout = useAccessLogout();
  const [currentView, setCurrentView] = useState(getCurrentView);

  useEffect(() => {
    const handleLocationChange = () => setCurrentView(getCurrentView());
    window.addEventListener('popstate', handleLocationChange);
    return () => window.removeEventListener('popstate', handleLocationChange);
  }, []);

  const navigate = (path: '/' | '/chat') => {
    if (window.location.pathname !== path) window.history.pushState(null, '', path);
    setCurrentView(getCurrentView());
  };

  const handleNavigateToChatbot = () => {
    navigate('/chat');
  };

  const handleBackToHome = () => {
    navigate('/');
  };

  return (
    <div className="App">
      {currentView === 'landing' ? (
        <LandingPage onGetStarted={handleNavigateToChatbot} onLogout={onLogout} />
      ) : (
        <NutriThriveChatbot onBackToHome={handleBackToHome} onLogout={onLogout} />
      )}
    </div>
  );
}

export default App;
