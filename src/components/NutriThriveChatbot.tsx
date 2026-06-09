import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { Menu } from 'lucide-react';
import { Chat, Message, NutriThriveChatbotProps } from '../types';
import {BackendService} from '../services/backendService';
import Sidebar from './Sidebar';
import ChatInput from './ChatInput';
import MessageComponent from './Message';

const NutriThriveChatbot: React.FC<NutriThriveChatbotProps> = ({ onBackToHome }) => {
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
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [backendConnected, setBackendConnected] = useState<boolean | null>(null);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const backendService = BackendService.getInstance();

  const currentChat = chats.find(chat => chat.id === currentChatId);
  
  // Use useMemo to prevent unnecessary recalculations
  const messages = useMemo(() => currentChat?.messages || [], [currentChat]);

  // Build conversation history for context
  const conversationHistory = useMemo(() => {
    return messages
      .filter(message => !message.isLoading)
      .map(message => ({
        role: message.role,
        content: message.content
      }));
  }, [messages]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Check backend connection on component mount
  useEffect(() => {
    const checkBackend = async () => {
      const connected = await backendService.checkHealth();
      setBackendConnected(connected);
    };
    
    checkBackend();
  }, [backendService]);

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
  const handleSend = useCallback(async () => {
    if (!input.trim() || isLoading || !currentChat) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input,
      timestamp: new Date()
    };

    // Update chat with user message
    const updatedChat = {
      ...currentChat,
      messages: [...currentChat.messages, userMessage],
      title: currentChat.messages.length === 1 ? input.slice(0, 30) + '...' : currentChat.title
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
      const historyForBackend = currentChat.messages
        .filter(msg => !msg.isLoading)
        .map(msg => ({
          role: msg.role,
          content: msg.content
        }));

      console.log('📝 Sending conversation history:', {
        length: historyForBackend.length,
        messages: historyForBackend.map(m => ({ role: m.role, content: m.content.slice(0, 50) + '...' }))
      });

      // Pass conversation history to backend
      const { recipes, backendData } = await backendService.searchRecipes(
        input, 
        historyForBackend
      );
      setBackendConnected(true);
      
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
      setBackendConnected(false);
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
  }, [input, isLoading, currentChat, currentChatId, backendService]);

  // Handle Enter key in input
  const handleKeyPress = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

  return (
    <div className="chat-shell flex">
      <div className="pointer-events-none absolute inset-0 soft-grid opacity-40" />
      {/* Sidebar */}
      <Sidebar
        chats={chats}
        currentChatId={currentChatId}
        sidebarOpen={sidebarOpen}
        showUserMenu={showUserMenu}
        onNewChat={createNewChat}
        onSelectChat={setCurrentChatId}
        onToggleUserMenu={() => setShowUserMenu(!showUserMenu)}
        onBackToHome={onBackToHome}
      />

      {/* Main Chat Area */}
      <div className="relative z-10 flex-1 min-w-0 h-full overflow-hidden">
        <div className="flex h-full flex-col overflow-hidden">
        {/* Header */}
        <div className="shrink-0 px-6 pt-4 pb-3">
          <div className="glass-panel rounded-[28px] px-6 py-5 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <button
                onClick={() => setSidebarOpen(!sidebarOpen)}
                className="text-slate-600 hover:text-slate-900 p-2.5 hover:bg-white rounded-2xl transition-colors border border-transparent hover:border-slate-200"
              >
                <Menu className="w-6 h-6" />
              </button>
              <div>
                <h1 className="font-semibold text-xl text-slate-900">Thrivewell Recipe Assistant</h1>
                <p className="text-sm text-slate-500">Focused, conversational nutrition guidance with backend grounding</p>
              </div>
            </div>
            
            <div className="flex items-center gap-2">
              <div className="hidden sm:block text-xs text-slate-400">
                {conversationHistory.length > 1 && `${conversationHistory.length} messages`}
              </div>
              <div className={`flex items-center gap-2 text-sm rounded-full px-3 py-2 border ${
                backendConnected === true ? 'text-emerald-700 bg-emerald-50 border-emerald-100' : 
                backendConnected === false ? 'text-rose-700 bg-rose-50 border-rose-100' : 'text-amber-700 bg-amber-50 border-amber-100'
              }`}>
                <div className={`w-2 h-2 rounded-full ${
                  backendConnected === true ? 'bg-emerald-500' : 
                  backendConnected === false ? 'bg-rose-500' : 'bg-amber-500'
                }`} />
                {backendConnected === true ? 'Connected' : 
                 backendConnected === false ? 'Offline' : 'Connecting...'}
              </div>
            </div>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 min-h-0 overflow-y-auto px-6 custom-scrollbar">
          <div className="max-w-4xl mx-auto pb-6 space-y-8">
            {messages.map(message => (
              <MessageComponent key={message.id} message={message} />
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input */}
        <div className="shrink-0">
          <ChatInput
            input={input}
            isLoading={isLoading}
            onInputChange={setInput}
            onSend={handleSend}
            onKeyPress={handleKeyPress}
          />
        </div>
        </div>
      </div>
    </div>
  );
};

export default NutriThriveChatbot;
