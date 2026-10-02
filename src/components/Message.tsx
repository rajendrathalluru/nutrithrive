import React from 'react';
import { ExternalLink, Loader2, MessageCircle, Phone, Leaf } from 'lucide-react';
import { Message as MessageType } from '../types';
import RecipeCard from './RecipeCard';
import { cleanBackendText } from '../utils/textCleaner';

interface MessageProps {
  message: MessageType;
}

const Message: React.FC<MessageProps> = ({ message }) => {
  const cleanedContent = cleanBackendText(message.content);
  const isSafetyRedirect = Boolean(message.backendData?.safety_redirect);

  return (
    <article className={`tw-message tw-message-${message.role}`} aria-label={`${message.role === 'user' ? 'Your' : 'Thrivewell'} message`}>
      {message.role === 'assistant' && <div className="tw-assistant-avatar"><Leaf size={17} aria-hidden="true" /></div>}
      
      <div className="tw-message-body">
        <div className="tw-message-meta">
          <span>
            {message.role === 'user' ? 'You' : 'Thrivewell'}
          </span>
          <time dateTime={message.timestamp.toISOString()}>
            {message.timestamp.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
          </time>
        </div>

        <div
          role={isSafetyRedirect ? 'alert' : undefined}
          className={`tw-message-content ${isSafetyRedirect ? 'tw-safety-message' : ''}`}
        >
          {message.isLoading ? (
            <div className="tw-loading" role="status">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Searching for recipes...</span>
            </div>
          ) : (
            <p className="whitespace-pre-wrap leading-7 text-[15px]">{cleanedContent}</p>
          )}

          {isSafetyRedirect && !message.isLoading && (
            <div className="mt-5 flex flex-wrap gap-2 border-t border-rose-200 pt-4">
              <a
                href="tel:988"
                className="inline-flex items-center gap-2 rounded-xl bg-rose-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-rose-800"
              >
                <Phone className="h-4 w-4" />
                Call 988
              </a>
              <a
                href="sms:988"
                className="inline-flex items-center gap-2 rounded-xl border border-rose-300 bg-white px-4 py-2.5 text-sm font-semibold text-rose-800 hover:bg-rose-100"
              >
                <MessageCircle className="h-4 w-4" />
                Text 988
              </a>
              <a
                href="https://findahelpline.com"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-800 hover:bg-slate-100"
              >
                International help
                <ExternalLink className="h-4 w-4" />
              </a>
            </div>
          )}
        </div>
        
        {/* Display backend analysis if available */}
        {message.backendData?.intent_analysis && (
          <details className="tw-search-analysis">
            <summary>Search Analysis</summary>
            <div className="text-slate-600 mt-2">
              {cleanBackendText(message.backendData.intent_analysis.search_strategy.primary_focus)}
            </div>
            {message.backendData.intent_analysis.constraints.equipment_only?.includes('microwave') && (
              <div className="text-slate-700 mt-2">Microwave-only recipes prioritized</div>
            )}
          </details>
        )}
        
        {message.recipes && message.recipes.length > 0 && (
          <div className="tw-recipes mt-5">
            <div className="mb-3 px-1">
              <h3 className="font-semibold text-slate-900">
                Recipes ({message.recipes.length})
              </h3>
            </div>
            <div className="grid gap-4">
              {message.recipes.map(recipe => (
                <RecipeCard key={recipe.id} recipe={recipe} />
              ))}
            </div>
          </div>
        )}
        
      </div>
    </article>
  );
};

export default Message;
