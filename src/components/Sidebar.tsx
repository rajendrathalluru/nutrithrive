import React from 'react';
import { Plus, LogOut, Settings, ChevronDown, MessageSquareText, Sparkles } from 'lucide-react';
import { Chat } from '../types';

interface SidebarProps {
  chats: Chat[];
  currentChatId: string;
  sidebarOpen: boolean;
  showUserMenu: boolean;
  onNewChat: () => void;
  onSelectChat: (chatId: string) => void;
  onToggleUserMenu: () => void;
  onBackToHome?: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({
  chats,
  currentChatId,
  sidebarOpen,
  showUserMenu,
  onNewChat,
  onSelectChat,
  onToggleUserMenu,
  onBackToHome
}) => {
  if (!sidebarOpen) return null;

  return (
    <aside className="glass-panel w-[300px] lg:w-[320px] h-[calc(100vh-2rem)] m-4 mr-0 rounded-[28px] flex flex-col overflow-hidden max-md:absolute max-md:inset-y-0 max-md:left-0 max-md:z-20 max-md:h-[calc(100vh-1.5rem)] max-md:m-3 max-md:mr-0">
      <div className="px-5 pt-5 pb-4 border-b border-slate-200/70">
        <div className="mb-5 flex items-start justify-between gap-3">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-400">Workspace</div>
            <h2 className="mt-2 text-xl font-semibold text-slate-900">Thrivewell AI</h2>
            <p className="mt-1 text-sm text-slate-500">Research-grade recipe guidance for care journeys.</p>
          </div>
          <div className="rounded-2xl bg-slate-900 p-2.5 text-white shadow-lg shadow-slate-900/20">
            <Sparkles className="w-5 h-5" />
          </div>
        </div>
        <button
          onClick={onNewChat}
          className="w-full rounded-2xl bg-slate-900 hover:bg-slate-800 text-white py-3.5 px-4 flex items-center justify-center gap-2 transition-colors font-medium shadow-lg shadow-slate-900/15"
        >
          <Plus className="w-5 h-5" />
          New Chat
        </button>
      </div>
      
      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4 custom-scrollbar">
        <div className="px-2 pb-3 text-[11px] uppercase tracking-[0.2em] text-slate-400">
          Recent Conversations
        </div>
        <div className="space-y-2">
          {chats.map(chat => (
            <button
              key={chat.id}
              onClick={() => onSelectChat(chat.id)}
              className={`w-full text-left p-3.5 rounded-2xl transition-all duration-200 border ${
                chat.id === currentChatId 
                  ? 'bg-slate-900 text-white border-slate-900 shadow-lg shadow-slate-900/10' 
                  : 'bg-white/55 border-transparent text-slate-600 hover:bg-white hover:border-slate-200 hover:text-slate-900'
              }`}
            >
              <div className="flex items-start gap-3">
                <div className={`mt-0.5 rounded-xl p-2 ${
                  chat.id === currentChatId ? 'bg-white/10 text-white' : 'bg-slate-100 text-slate-500'
                }`}>
                  <MessageSquareText className="w-4 h-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="font-medium truncate text-sm">{chat.title}</div>
                  <div className={`mt-1 text-xs ${
                    chat.id === currentChatId ? 'text-slate-300' : 'text-slate-400'
                  }`}>
                    {chat.messages.length} messages
                  </div>
                </div>
              </div>
              <div className={`mt-3 text-xs ${
                chat.id === currentChatId ? 'text-slate-400' : 'text-slate-400'
              }`}>
                {chat.timestamp.toLocaleDateString()}
              </div>
            </button>
          ))}
        </div>
      </div>
      
      <div className="p-4 border-t border-slate-200/70 bg-white/50">
        <div className="relative">
          <button
            onClick={onToggleUserMenu}
            className="w-full flex items-center gap-3 p-3 rounded-2xl hover:bg-white transition-colors border border-transparent hover:border-slate-200"
          >
            <div className="w-10 h-10 bg-slate-900 rounded-2xl flex items-center justify-center text-white font-medium shadow-md shadow-slate-900/10">
              U
            </div>
            <div className="flex-1 text-left">
              <div className="text-sm font-medium text-slate-900">User</div>
              <div className="text-xs text-slate-400">Assistant workspace</div>
            </div>
            <ChevronDown className="w-4 h-4 text-slate-500" />
          </button>
          
          {showUserMenu && (
            <div className="absolute bottom-full mb-2 left-0 right-0 glass-panel rounded-2xl p-2">
              <button className="w-full text-left p-3 hover:bg-slate-50 rounded-xl flex items-center gap-2 text-slate-700">
                <Settings className="w-4 h-4" />
                Settings
              </button>
              <button 
                onClick={onBackToHome}
                className="w-full text-left p-3 hover:bg-slate-50 rounded-xl flex items-center gap-2 text-slate-700"
              >
                <LogOut className="w-4 h-4" />
                Back to Home
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
