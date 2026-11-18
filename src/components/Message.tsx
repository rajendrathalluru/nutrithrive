import React from 'react';
import { ExternalLink, Loader2, MessageCircle, Phone, Leaf } from 'lucide-react';
import { Message as MessageType } from '../types';
import RecipeCard from './RecipeCard';
import { cleanBackendText } from '../utils/textCleaner';

interface MessageProps {
  message: MessageType;
}

const splitBullet = (raw: string): { title: string; detail: string } => {
  const emDashIdx = raw.indexOf(' — ');
  const colonIdx = raw.indexOf(': ');
  let sepIdx = -1;
  let sepLen = 0;

  if (emDashIdx !== -1 && (colonIdx === -1 || emDashIdx < colonIdx)) {
    sepIdx = emDashIdx;
    sepLen = 3;
  } else if (colonIdx !== -1) {
    sepIdx = colonIdx;
    sepLen = 2;
  }

  if (sepIdx === -1) {
    return { title: raw, detail: '' };
  }

  return {
    title: raw.slice(0, sepIdx),
    detail: raw.slice(sepIdx + sepLen),
  };
};

const renderFormattedContent = (content: string): React.ReactNode => {
  const lines = content
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines.some((line) => line.startsWith('• '))) {
    return <p className="whitespace-pre-wrap leading-7 text-[15px]">{content}</p>;
  }

  const blocks: React.ReactNode[] = [];
  let bulletBuffer: string[] = [];
  let seenBullets = false;

  const flushBullets = (keyPrefix: string) => {
    if (bulletBuffer.length === 0) return;
    blocks.push(
      <ul key={`${keyPrefix}-list`} className="my-2.5 space-y-2" aria-label="Recipe highlights">
        {bulletBuffer.map((rawBullet, idx) => {
          const { title, detail } = splitBullet(rawBullet);
          return (
            <li
              key={idx}
              className="flex items-start gap-2.5 rounded-xl border border-[#e2e9dc] bg-[#f4f7f1] px-3.5 py-2.5 text-[14px] leading-6"
            >
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[#56774e]" aria-hidden="true" />
              <div>
                <strong className="font-semibold text-slate-900">{title}</strong>
                {detail && <span className="text-slate-600"> — {detail}</span>}
              </div>
            </li>
          );
        })}
      </ul>
    );
    bulletBuffer = [];
  };

  lines.forEach((line, idx) => {
    if (line.startsWith('• ')) {
      seenBullets = true;
      bulletBuffer.push(line.slice(2).trim());
      return;
    }

    flushBullets(`block-${idx}`);
    if (!seenBullets) {
      blocks.push(
        <p key={`intro-${idx}`} className="text-[15px] font-medium text-slate-800 mb-2.5">
          {line}
        </p>
      );
    } else if (line.startsWith('Open ')) {
      blocks.push(
        <p key={`outro-${idx}`} className="mt-2 text-xs text-slate-500">
          {line}
        </p>
      );
    } else {
      blocks.push(
        <p key={`note-${idx}`} className="mt-2 text-sm text-slate-600 leading-6">
          {line}
        </p>
      );
    }
  });

  flushBullets('end');

  return <div>{blocks}</div>;
};

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
              <span>{message.progressMessage || 'Waiting for the recipe service…'}</span>
            </div>
          ) : (
            renderFormattedContent(cleanedContent)
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
        
        {!message.isLoading && message.recipes && message.recipes.length > 0 && (
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
