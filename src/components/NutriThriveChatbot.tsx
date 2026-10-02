import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { PanelLeft, Leaf } from 'lucide-react';
import { BackendHealth, Chat, Message, NutriThriveChatbotProps } from '../types';
import {BackendService} from '../services/backendService';
import Sidebar from './Sidebar';
import ChatInput from './ChatInput';
import AssistantChatThread from './AssistantChatThread';
import { buildConversationHistory } from '../utils/conversationHistory';
import { useChatViewport } from '../hooks/useChatViewport';
import './ChatWorkspace.css';

const NutriThriveChatbot: React.FC<NutriThriveChatbotProps> = ({ onBackToHome }) => {
  const shellRef = useChatViewport();
  const [chats, setChats] = useState<Chat[]>([
    {
      id: '1',
      title: 'New Chat',
      messages: [
        {
          id: '1',
          role: 'assistant',
          content: "Hi! I'm here to help you find personalized recipes for your cancer journey. Tell me about your dietary needs, any side effects you're managing, or what type of meal you're looking for.",
          timestamp: new Date(),
        }
      ],
      timestamp: new Date()
    }
  ]);
  
  const [currentChatId, setCurrentChatId] = useState('1');
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.matchMedia('(min-width: 768px)').matches);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [backendHealth, setBackendHealth] = useState<BackendHealth>({
    status: 'starting',
    message: 'Recipe engine is warming up',
    model_loaded: false,
    recipes_count: 0,
    startup_in_progress: true,
    initialization_error: null
  });
  
  const backendService = BackendService.getInstance();

  const currentChat = chats.find(chat => chat.id === currentChatId);
  
  // Use useMemo to prevent unnecessary recalculations
  const messages = useMemo(() => currentChat?.messages || [], [currentChat]);

  useEffect(() => {
    if (!sidebarOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSidebarOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [sidebarOpen]);

  useEffect(() => {
    let cancelled = false;

    const pollBackendHealth = async () => {
      const nextHealth = await backendService.getHealth();
      if (!cancelled) {
        setBackendHealth(nextHealth);
      }
    };

    void pollBackendHealth();
    const intervalId = window.setInterval(() => {
      void pollBackendHealth();
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [backendService]);

  const backendReady = backendHealth.status === 'healthy';
  const backendStatusMessage = backendHealth.status === 'starting'
    ? 'Recipe engine is warming up'
    : backendHealth.message;

  const createNewChat = () => {
    const newChat: Chat = {
      id: Date.now().toString(),
      title: 'New Chat',
      messages: [
        {
          id: Date.now().toString(),
          role: 'assistant',
          content: "Hi! I'm here to help you find personalized recipes for your cancer journey. Tell me about your dietary needs, any side effects you're managing, or what type of meal you're looking for.",
          timestamp: new Date(),
        }
      ],
      timestamp: new Date()
    };
    
    setChats(prev => [newChat, ...prev]);
    setCurrentChatId(newChat.id);
    setInput('');
  };

  // Use useCallback to memoize the send function
  const handleSend = useCallback(async (messageText: string = input) => {
    if (!messageText.trim() || isLoading || !currentChat || !backendReady) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: messageText,
      timestamp: new Date()
    };

    // Update chat with user message
    const updatedChat = {
      ...currentChat,
      messages: [...currentChat.messages, userMessage],
      title: currentChat.messages.length === 1 ? messageText.slice(0, 30) + '...' : currentChat.title
    };

    setChats(prev => prev.map(chat => 
      chat.id === currentChatId ? updatedChat : chat
    ));

    setInput('');
    setIsLoading(true);

    // Add loading message
    const loadingMessage: Message = {
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isLoading: true
    };
    
    setChats(prev => prev.map(chat => 
      chat.id === currentChatId 
        ? { ...chat, messages: [...chat.messages, loadingMessage] }
        : chat
    ));

    try {
      // Build conversation history excluding the current user message and loading messages
      const historyForBackend = buildConversationHistory(currentChat.messages);

      // Pass conversation history to backend
      const { recipes, backendData } = await backendService.searchRecipes(
        messageText,
        historyForBackend
      );
      setBackendHealth((previous) => ({
        ...previous,
        status: 'healthy',
        message: 'Service is running',
        model_loaded: true
      }));
      
      // Use the exact response content from backend
      const responseContent = backendData?.response || 
        (recipes.length > 0 
          ? `I found ${recipes.length} recipe${recipes.length > 1 ? 's' : ''} that match your needs.`
          : "I couldn't find specific recipes matching your request. Could you provide more details?"
        );

      const responseMessage: Message = {
        id: (Date.now() + 2).toString(),
        role: 'assistant',
        content: responseContent,
        timestamp: new Date(),
        recipes: recipes,
        backendData: backendData
      };

      setChats(prev => prev.map(chat => 
        chat.id === currentChatId 
          ? { 
              ...chat, 
              messages: chat.messages.filter(m => !m.isLoading).concat(responseMessage)
            }
          : chat
      ));
    } catch (error) {
      setBackendHealth({
        status: 'offline',
        message: 'Recipe service is offline.',
        model_loaded: false,
        recipes_count: 0,
        initialization_error: error instanceof Error ? error.message : null
      });
      const errorText = error instanceof Error
        ? error.message
        : `Unable to connect to the backend service at ${backendService.getBaseUrl()}.`;

      const errorMessage: Message = {
        id: (Date.now() + 2).toString(),
        role: 'assistant',
        content: `I’m having trouble reaching the recipe service. ${errorText}`,
        timestamp: new Date(),
        recipes: []
      };

      setChats(prev => prev.map(chat => 
        chat.id === currentChatId 
          ? { 
              ...chat, 
              messages: chat.messages.filter(m => !m.isLoading).concat(errorMessage)
            }
          : chat
      ));
    } finally {
      setIsLoading(false);
    }
  }, [input, isLoading, currentChat, currentChatId, backendReady, backendService]);

  // Handle Enter key in input
  const handleKeyPress = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

  const closeMobileSidebar = () => {
    if (window.matchMedia('(max-width: 767px)').matches) setSidebarOpen(false);
  };

  return (
    <div ref={shellRef} className="chat-shell thrive-chat">
      {sidebarOpen && <button className="tw-sidebar-backdrop" aria-label="Close conversation sidebar" onClick={() => setSidebarOpen(false)} />}
      <Sidebar
        chats={chats}
        currentChatId={currentChatId}
        sidebarOpen={sidebarOpen}
        showUserMenu={showUserMenu}
        onNewChat={() => { createNewChat(); closeMobileSidebar(); }}
        onSelectChat={chatId => { setCurrentChatId(chatId); closeMobileSidebar(); }}
        onClose={() => setSidebarOpen(false)}
        onToggleUserMenu={() => setShowUserMenu(!showUserMenu)}
        onBackToHome={onBackToHome}
      />

      <main className="tw-main">
        <header className="tw-header">
          <div className="tw-header-title">
            <button type="button" onClick={() => setSidebarOpen(!sidebarOpen)} className="tw-icon-button" aria-label="Toggle conversations" aria-expanded={sidebarOpen} aria-controls="conversation-sidebar">
              <PanelLeft size={20} aria-hidden="true" />
            </button>
            <div>
              <h1>Recipe assistant</h1>
              <p>Good food, with you in mind</p>
            </div>
          </div>
          <div className={`tw-health tw-health-${backendHealth.status}`} role="status" title={backendStatusMessage}>
            <span className="tw-health-dot" />
            {backendReady ? 'Connected' : backendHealth.status === 'starting' ? 'Warming up' : 'Offline'}
          </div>
        </header>
        <AssistantChatThread
          key={currentChatId}
          messages={messages}
          disabled={!backendReady || isLoading}
          onSend={handleSend}
          onSuggestion={text => {
            setInput(text);
            document.getElementById('recipe-message-input')?.focus();
          }}
        />
        <ChatInput
            input={input}
            isLoading={isLoading}
            backendReady={backendReady}
            backendStatusMessage={backendStatusMessage}
            onInputChange={setInput}
            onSend={() => { void handleSend(); }}
            onKeyPress={handleKeyPress}
        />
        <div className="tw-disclaimer"><Leaf size={12} aria-hidden="true" /> Recipe ideas, not a substitute for medical advice.</div>
      </main>
    </div>
  );
};

export default NutriThriveChatbot;
