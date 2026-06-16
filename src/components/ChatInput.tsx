import React, { useEffect, useRef } from 'react';
import { Send, Loader2, CornerDownLeft } from 'lucide-react';

interface ChatInputProps {
  input: string;
  isLoading: boolean;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onKeyPress: (e: React.KeyboardEvent) => void;
}

const ChatInput: React.FC<ChatInputProps> = ({
  input,
  isLoading,
  onInputChange,
  onSend
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = '56px';
    const nextHeight = Math.min(textarea.scrollHeight, 200);
    textarea.style.height = `${Math.max(nextHeight, 56)}px`;
  }, [input]);

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <div className="px-4 pb-4 pt-3 sm:px-6 sm:pb-6">
      <div className="max-w-4xl mx-auto">
        <div className="glass-panel rounded-[30px] border border-slate-200/80 bg-white/90 px-3 py-3 shadow-[0_18px_45px_rgba(15,23,42,0.08)] sm:px-4 sm:py-4">
          <div className="flex items-end gap-3">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => onInputChange(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Describe your dietary needs, ingredients available, or ask for recipe ideas..."
              className="min-w-0 w-full flex-1 resize-none overflow-y-auto bg-transparent px-2 py-2 text-lg leading-8 text-slate-800 placeholder:text-slate-400 focus:outline-none"
              rows={1}
              style={{
                minHeight: '56px',
                maxHeight: '200px',
              }}
            />
            <button
              onClick={onSend}
              disabled={!input.trim() || isLoading}
              className="mb-1 flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-slate-900 text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300 shadow-lg shadow-slate-900/15"
              aria-label="Send message"
            >
              {isLoading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <Send className="h-5 w-5 fill-current" />
              )}
            </button>
          </div>
          <div className="mt-2 flex items-center justify-between px-1 text-xs text-slate-400">
            <span className="truncate">Grounded recipe search with backend context</span>
            <span className="ml-3 inline-flex shrink-0 items-center gap-1">
              <CornerDownLeft className="w-3.5 h-3.5" />
              Enter to send
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ChatInput;
