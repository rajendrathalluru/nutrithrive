import React, { useEffect, useRef, useState } from 'react';
import { Send, Loader2, CornerDownLeft, Mic, Square } from 'lucide-react';

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
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const finalTranscriptRef = useRef('');
  const [isListening, setIsListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [voiceError, setVoiceError] = useState('');

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = '56px';
    const nextHeight = Math.min(textarea.scrollHeight, 140);
    textarea.style.height = `${Math.max(nextHeight, 56)}px`;
  }, [input]);

  useEffect(() => {
    const SpeechRecognitionApi = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognitionApi) {
      setVoiceSupported(false);
      return;
    }

    const recognition = new SpeechRecognitionApi();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let finalTranscript = finalTranscriptRef.current;
      let interimTranscript = '';

      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const transcriptPart = event.results[i][0]?.transcript ?? '';
        if (event.results[i].isFinal) {
          finalTranscript = `${finalTranscript} ${transcriptPart}`.trim();
        } else {
          interimTranscript = `${interimTranscript} ${transcriptPart}`.trim();
        }
      }

      finalTranscriptRef.current = finalTranscript;
      onInputChange(`${finalTranscript}${interimTranscript ? ` ${interimTranscript}` : ''}`.trim());
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error !== 'no-speech') {
        setVoiceError('Voice input is temporarily unavailable.');
      }
      setIsListening(false);
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognitionRef.current = recognition;
    setVoiceSupported(true);

    return () => {
      recognition.abort();
      recognitionRef.current = null;
    };
  }, [onInputChange]);

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  const handleToggleVoice = () => {
    const recognition = recognitionRef.current;
    if (!recognition) {
      setVoiceError('Voice input is not supported in this browser.');
      return;
    }

    setVoiceError('');

    if (isListening) {
      recognition.stop();
      setIsListening(false);
      return;
    }

    finalTranscriptRef.current = input.trim();
    recognition.start();
    setIsListening(true);
  };

  return (
    <div className="px-4 pb-4 pt-3 sm:px-6 sm:pb-6">
      <div className="max-w-4xl mx-auto">
        <div className="glass-panel rounded-[32px] border border-slate-200/70 bg-white/92 px-4 py-3 shadow-[0_18px_45px_rgba(15,23,42,0.08)] sm:px-5">
          <div className="flex items-end gap-3">
            {voiceSupported && (
              isListening ? (
                <button
                  type="button"
                  onClick={handleToggleVoice}
                  className="mb-1 flex h-12 shrink-0 items-center gap-3 rounded-2xl bg-slate-900 px-3 text-white transition-colors hover:bg-slate-800"
                  aria-label="Stop voice input"
                  title="Stop voice input"
                >
                  <div className="flex items-end gap-1">
                    {[14, 22, 18, 26, 16, 24].map((height, index) => (
                      <span
                        key={height}
                        className="block w-1 rounded-full bg-white/90 animate-pulse"
                        style={{
                          height: `${height}px`,
                          animationDelay: `${index * 0.08}s`,
                          animationDuration: '0.9s'
                        }}
                      />
                    ))}
                  </div>
                  <Square className="h-4 w-4 fill-current" />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleToggleVoice}
                  className="mb-1 flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-600 transition-colors hover:bg-slate-200"
                  aria-label="Start voice input"
                  title="Start voice input"
                >
                  <Mic className="h-5 w-5" />
                </button>
              )
            )}
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => onInputChange(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Describe your dietary needs, ingredients available, or ask for recipe ideas..."
              className="min-w-0 w-full flex-1 resize-none overflow-hidden bg-transparent px-1 py-2 text-lg leading-8 text-slate-800 placeholder:text-slate-400 focus:outline-none"
              rows={1}
              style={{
                minHeight: '56px',
                maxHeight: '140px',
              }}
            />
            {!isListening && (
              <button
                onClick={onSend}
                disabled={!input.trim() || isLoading}
                className="mb-1 flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300 shadow-lg shadow-slate-900/15"
                aria-label="Send message"
              >
                {isLoading ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  <Send className="h-5 w-5 fill-current" />
                )}
              </button>
            )}
          </div>
        </div>
        <div className="mt-2 flex items-center justify-between px-2 text-xs text-slate-400">
          <span className="truncate">
            {voiceError || (isListening ? 'Listening... tap the control again to stop' : 'Grounded recipe search with backend context')}
          </span>
          <span className="ml-3 inline-flex shrink-0 items-center gap-1">
            <CornerDownLeft className="w-3.5 h-3.5" />
            Enter to send
          </span>
        </div>
      </div>
    </div>
  );
};

export default ChatInput;
