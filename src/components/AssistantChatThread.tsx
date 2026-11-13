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
import { ArrowDown, ArrowRight, Soup, Leaf, CookingPot } from 'lucide-react';
import { Message } from '../types';
import MessageComponent from './Message';
import RecipeFollowUp from './RecipeFollowUp';

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
  { icon: Soup, prompt: 'Find a cozy one-pot dinner I can make tonight.' },
  { icon: Leaf, prompt: 'Show me a Mediterranean dinner with roasted vegetables.' },
  { icon: CookingPot, prompt: 'What can I make with chickpeas, spinach, and rice?' },
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
  const latest = messages[messages.length - 1];
  const previousRequest = messages.slice().reverse().find(message => message.role === 'user');
  const resolvedRequest = latest?.backendData?.intent_analysis?.resolved_query;
  const canRefine = latest?.role === 'assistant' && !!latest.recipes?.length && previousRequest;

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
              <section className="tw-suggestions" aria-label="Recipe conversation starters">
                <h3>Try a recipe prompt</h3>
                {suggestions.map(({ icon: Icon, prompt }) => (
                  <button key={prompt} type="button" disabled={disabled || isRunning} onClick={() => { void onSend(prompt); }}>
                    <Icon size={17} aria-hidden="true" />
                    <span>{prompt}</span><ArrowRight size={16} aria-hidden="true" />
                  </button>
                ))}
              </section>
            )}
            {!disabled && canRefine && latest.backendData?.follow_up && (
              <RecipeFollowUp key={latest.id} onDraft={onSuggestion} followUp={latest.backendData.follow_up}
                request={typeof resolvedRequest === 'string' && resolvedRequest.trim() ? resolvedRequest : previousRequest.content} />
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
