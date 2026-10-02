import React from 'react';
import { Plus, LogOut, Settings, ChevronUp, MessageSquareText, Leaf, PanelLeftClose } from 'lucide-react';
import { Chat } from '../types';

interface SidebarProps {
  chats: Chat[];
  currentChatId: string;
  sidebarOpen: boolean;
  showUserMenu: boolean;
  onNewChat: () => void;
  onSelectChat: (chatId: string) => void;
  onToggleUserMenu: () => void;
  onClose: () => void;
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
  onClose,
  onBackToHome
}) => {
  if (!sidebarOpen) return null;

  return (
    <aside id="conversation-sidebar" className="tw-sidebar" aria-label="Conversation sidebar">
      <div className="tw-sidebar-top">
        <div className="tw-brand-row">
          <div className="tw-brand"><Leaf size={23} aria-hidden="true" /><h2>Thrivewell<span>A little better, every day</span></h2></div>
          <button type="button" onClick={onClose} className="tw-icon-button" aria-label="Hide conversations"><PanelLeftClose size={18} aria-hidden="true" /></button>
        </div>
        <button
          onClick={onNewChat}
          className="tw-new-chat"
        >
          <Plus size={18} aria-hidden="true" />
          New Chat
          <span aria-hidden="true">↗</span>
        </button>
      </div>
      
      <nav className="tw-chat-nav custom-scrollbar" aria-label="Recent conversations">
        <h3 className="tw-eyebrow">Your conversations</h3>
        <div className="tw-chat-items">
          {chats.map(chat => (
            <button
              key={chat.id}
              onClick={() => onSelectChat(chat.id)}
              aria-current={chat.id === currentChatId ? 'page' : undefined}
              className="tw-chat-item"
            >
              <MessageSquareText size={16} aria-hidden="true" />
              <span className="tw-chat-item-text"><strong>{chat.title}</strong><small>{chat.messages.filter(message => !message.isLoading).length} messages · {chat.timestamp.toLocaleDateString()}</small></span>
            </button>
          ))}
        </div>
      </nav>
      
      <div className="tw-sidebar-footer">
        <div className="tw-sidebar-note"><Leaf size={17} aria-hidden="true" /><p>Small choices.<br /><strong>Everyday nourishment.</strong></p></div>
        <div className="relative">
          <button
            onClick={onToggleUserMenu}
            className="tw-user-button"
            aria-expanded={showUserMenu}
            aria-controls="workspace-options"
          >
            <span className="tw-user-avatar">U</span>
            <span className="tw-user-label">Your workspace<small>Recipe conversations</small></span>
            <ChevronUp size={15} aria-hidden="true" />
          </button>
          
          {showUserMenu && (
            <div id="workspace-options" className="tw-workspace-options">
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
