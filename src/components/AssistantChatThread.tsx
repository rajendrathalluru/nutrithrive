import React from 'react';
import {
  AssistantRuntimeProvider,
  getExternalStoreMessages,
  MessagePrimitive,
  ThreadMessageLike,
  ThreadPrimitive,
  useExternalStoreRuntime,
  useMessage,
} from '@assistant-ui/react';
import { ArrowDown, ArrowUpRight, Leaf } from 'lucide-react';
import { Message } from '../types';
import MessageComponent from './Message';

interface AssistantChatThreadProps {
  messages: Message[];
  disabled: boolean;
  onSend: (text: string) => Promise<void>;
  onSuggestion: (text: string) => void;
}

const convertMessage = (message: Message): ThreadMessageLike => ({
  id: message.id,
  role: message.role,
  content: message.content,
  createdAt: message.timestamp,
  ...(message.role === 'assistant' && {
    status: message.isLoading
      ? { type: 'running' as const }
      : { type: 'complete' as const, reason: 'stop' as const },
  }),
});

const ThreadMessage: React.FC = () => {
  const message = useMessage(state => getExternalStoreMessages<Message>(state)[0]);
  if (!message) return null;

  return (
    <MessagePrimitive.Root className="tw-thread-message">
      <MessageComponent message={message} />
    </MessagePrimitive.Root>
  );
};

const suggestions = [
  { title: 'Quick & easy', detail: 'For a busy day', prompt: 'Show recipes that take 30 minutes or less.' },
  { title: 'Plant-based ideas', detail: 'Something colorful', prompt: 'Show me some vegetarian dinner recipes.' },
  { title: 'Use what I have', detail: 'Start with my ingredients', prompt: 'Help me find recipes using the ingredients I have.' },
];

const AssistantChatThread: React.FC<AssistantChatThreadProps> = ({
  messages, disabled, onSend, onSuggestion,
}) => {
  const isRunning = messages.some(message => message.isLoading);
  const runtime = useExternalStoreRuntime({
    messages,
    convertMessage,
    isRunning,
    isDisabled: disabled,
    onNew: async message => {
      const text = message.content
        .flatMap(part => part.type === 'text' ? [part.text] : [])
        .join('\n');
      if (text.trim() && !disabled) await onSend(text);
    },
  });
  const isWelcome = messages.length === 1 && messages[0].role === 'assistant';

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className={`tw-thread ${isWelcome ? 'tw-thread-welcome' : ''}`}>
        <ThreadPrimitive.Viewport className="tw-viewport custom-scrollbar">
          <div className="tw-conversation">
            {isWelcome && (
              <div className="tw-welcome">
                <span className="tw-welcome-icon"><Leaf size={26} aria-hidden="true" /></span>
                <p className="tw-eyebrow">A little inspiration, a little nourishment</p>
                <h2>What sounds good today?</h2>
              </div>
            )}
            <div role="log" aria-label="Conversation" aria-live="polite" aria-busy={isRunning} className="tw-message-list">
              <ThreadPrimitive.Messages components={{ Message: ThreadMessage }} />
            </div>
            {isWelcome && (
              <div className="tw-suggestions" aria-label="Recipe conversation starters">
                {suggestions.map(suggestion => (
                  <button key={suggestion.title} type="button" onClick={() => onSuggestion(suggestion.prompt)}>
                    <span>{suggestion.title}<ArrowUpRight size={15} aria-hidden="true" /></span>
                    <small>{suggestion.detail}</small>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="tw-scroll-anchor">
            <ThreadPrimitive.ScrollToBottom className="tw-scroll-button" aria-label="Scroll to latest message" title="Scroll to latest message">
              <ArrowDown size={17} aria-hidden="true" />
            </ThreadPrimitive.ScrollToBottom>
          </div>
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
};

export default AssistantChatThread;
