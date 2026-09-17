import React from 'react';
import { ExternalLink, Loader2, MessageCircle, Phone, Sparkles, User2 } from 'lucide-react';
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
    <div className={`flex gap-4 ${message.role === 'user' ? 'flex-row-reverse' : ''}`}>
      <div className={`w-10 h-10 rounded-2xl flex items-center justify-center flex-shrink-0 shadow-sm ${
        message.role === 'user' ? 'bg-slate-900 text-white' : 'bg-white text-slate-700 border border-slate-200'
      }`}>
        {message.role === 'user' ? <User2 className="w-4 h-4" /> : <Sparkles className="w-4 h-4" />}
      </div>
      
      <div className="flex-1">
        <div className="mb-2 flex items-center gap-2 px-1">
          <span className="text-sm font-medium text-slate-900">
            {message.role === 'user' ? 'You' : 'Thrivewell'}
          </span>
          <span className="text-xs text-slate-400">
            {message.timestamp.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
          </span>
        </div>

        <div
          role={isSafetyRedirect ? 'alert' : undefined}
          className={`rounded-[24px] p-5 ${
          message.role === 'user' 
            ? 'bg-slate-900 text-white shadow-lg shadow-slate-900/10' 
            : isSafetyRedirect
              ? 'border-2 border-rose-200 bg-rose-50 text-slate-900 shadow-lg shadow-rose-900/5'
            : 'glass-panel text-slate-800'
          }`}
        >
          {message.isLoading ? (
            <div className="flex items-center gap-2 text-sm">
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
          <div className="mt-3 rounded-2xl border border-slate-200 bg-white/70 p-4 text-sm">
            <div className="font-medium text-slate-700 mb-1">Search Analysis</div>
            <div className="text-slate-500">
              {cleanBackendText(message.backendData.intent_analysis.search_strategy.primary_focus)}
            </div>
            {message.backendData.intent_analysis.constraints.equipment_only?.includes('microwave') && (
              <div className="text-slate-700 mt-2">Microwave-only recipes prioritized</div>
            )}
          </div>
        )}
        
        {message.recipes && message.recipes.length > 0 && (
          <div className="mt-4">
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
    </div>
  );
};

export default Message;
