import React, { useEffect, useRef, useState } from 'react';
import { Send, Loader2, CornerDownLeft, Mic, Square } from 'lucide-react';
import { BackendService } from '../services/backendService';

interface ChatInputProps {
  input: string;
  isLoading: boolean;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onKeyPress: (e: React.KeyboardEvent) => void;
}

const backendService = BackendService.getInstance();

const ChatInput: React.FC<ChatInputProps> = ({
  input,
  isLoading,
  onInputChange,
  onSend
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const voiceBaseInputRef = useRef('');
  const usingLiveRecognitionRef = useRef(false);

  const [isListening, setIsListening] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [voiceError, setVoiceError] = useState('');
  const [isCompactPlaceholder, setIsCompactPlaceholder] = useState(false);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = '56px';
    const nextHeight = Math.min(textarea.scrollHeight, 140);
    textarea.style.height = `${Math.max(nextHeight, 56)}px`;
  }, [input]);

  useEffect(() => {
    const SpeechRecognitionApi = window.SpeechRecognition || window.webkitSpeechRecognition;
    const supportsLiveRecognition = !!SpeechRecognitionApi;
    const supportsRecordedAudio =
      typeof window !== 'undefined'
      && typeof navigator !== 'undefined'
      && !!navigator.mediaDevices?.getUserMedia
      && typeof MediaRecorder !== 'undefined';

    if (SpeechRecognitionApi) {
      const recognition = new SpeechRecognitionApi();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = 'en-US';

      recognition.onresult = (event: SpeechRecognitionEvent) => {
        let finalTranscript = '';
        let interimTranscript = '';

        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const transcriptPart = event.results[index][0]?.transcript?.trim() ?? '';
          if (!transcriptPart) {
            continue;
          }

          if (event.results[index].isFinal) {
            finalTranscript = `${finalTranscript} ${transcriptPart}`.trim();
          } else {
            interimTranscript = `${interimTranscript} ${transcriptPart}`.trim();
          }
        }

        const liveTranscript = [finalTranscript, interimTranscript].filter(Boolean).join(' ').trim();
        const nextValue = [voiceBaseInputRef.current, liveTranscript].filter(Boolean).join(' ').trim();
        onInputChange(nextValue);
      };

      recognition.onerror = () => {
        setVoiceError('Live voice preview is unavailable. Falling back to transcription after recording.');
        setIsListening(false);
      };

      recognition.onend = () => {
        if (usingLiveRecognitionRef.current) {
          setIsListening(false);
        }
      };

      recognitionRef.current = recognition;
    }

    setVoiceSupported(supportsLiveRecognition || supportsRecordedAudio);

    return () => {
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    };
  }, [onInputChange]);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 640px)');
    const updatePlaceholderMode = () => setIsCompactPlaceholder(mediaQuery.matches);

    updatePlaceholderMode();
    mediaQuery.addEventListener('change', updatePlaceholderMode);

    return () => {
      mediaQuery.removeEventListener('change', updatePlaceholderMode);
    };
  }, []);

  useEffect(() => () => {
    recognitionRef.current?.abort();
    mediaRecorderRef.current?.stop();
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
  }, []);

  const getSupportedMimeType = () => {
    const candidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/mp4',
      'audio/mpeg',
    ];

    return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || '';
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!isListening && !isTranscribing) {
        onSend();
      }
    }
  };

  const cleanupRecorder = () => {
    mediaRecorderRef.current = null;
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    audioChunksRef.current = [];
  };

  const transcribeRecordedAudio = async (audioBlob: Blob) => {
    try {
      setIsTranscribing(true);
      setVoiceError('');

      const transcript = await backendService.transcribeAudio(audioBlob);

      if (!transcript) {
        setVoiceError('No speech was detected. Please try again.');
        return;
      }

      const nextValue = [voiceBaseInputRef.current, transcript].filter(Boolean).join(' ').trim();
      onInputChange(nextValue);
    } catch (error) {
      const message = error instanceof Error
        ? error.message
        : 'Voice transcription is temporarily unavailable.';
      setVoiceError(message);
    } finally {
      setIsTranscribing(false);
    }
  };

  const startRecordedAudioMode = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = getSupportedMimeType();
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);

      audioChunksRef.current = [];
      mediaStreamRef.current = stream;
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.onerror = () => {
        setVoiceError('Voice recording failed. Please try again.');
        setIsListening(false);
        cleanupRecorder();
      };

      recorder.onstop = async () => {
        setIsListening(false);

        const audioBlob = new Blob(
          audioChunksRef.current,
          { type: recorder.mimeType || 'audio/webm' }
        );

        cleanupRecorder();

        if (audioBlob.size > 0) {
          await transcribeRecordedAudio(audioBlob);
        }
      };

      recorder.start();
      usingLiveRecognitionRef.current = false;
      setIsListening(true);
    } catch {
      setVoiceError('Microphone access was denied or unavailable.');
      setIsListening(false);
      cleanupRecorder();
    }
  };

  const startVoiceInput = async () => {
    if (!voiceSupported || isTranscribing) {
      setVoiceError('Voice input is not supported in this browser.');
      return;
    }

    setVoiceError('');
    voiceBaseInputRef.current = input.trim();

    const recognition = recognitionRef.current;
    if (recognition) {
      try {
        usingLiveRecognitionRef.current = true;
        recognition.start();
        setIsListening(true);
        return;
      } catch {
        usingLiveRecognitionRef.current = false;
      }
    }

    await startRecordedAudioMode();
  };

  const stopVoiceInput = () => {
    if (usingLiveRecognitionRef.current && recognitionRef.current) {
      recognitionRef.current.stop();
      setIsListening(false);
      return;
    }

    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === 'inactive') {
      setIsListening(false);
      cleanupRecorder();
      return;
    }

    recorder.stop();
  };

  const handleToggleVoice = () => {
    if (isListening) {
      stopVoiceInput();
      return;
    }

    startVoiceInput();
  };

  const placeholderText = isCompactPlaceholder
    ? 'Ask for recipes or ingredients...'
    : 'Describe your dietary needs, ingredients available, or ask for recipe ideas...';

  const statusText = voiceError
    || (isTranscribing
      ? 'Transcribing your voice note...'
      : isListening
        ? usingLiveRecognitionRef.current
          ? 'Listening live... your words appear as you speak'
          : 'Listening... tap again to stop and transcribe'
        : 'Grounded recipe search with backend context');

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
                  disabled={isTranscribing}
                  className="mb-1 flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-600 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-300"
                  aria-label="Start voice input"
                  title="Start voice input"
                >
                  {isTranscribing ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : (
                    <Mic className="h-5 w-5" />
                  )}
                </button>
              )
            )}
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => onInputChange(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder={placeholderText}
              disabled={isTranscribing}
              className="min-w-0 w-full flex-1 resize-none overflow-hidden bg-transparent px-1 py-2 text-base leading-7 text-slate-800 placeholder:text-slate-400 focus:outline-none disabled:cursor-wait sm:text-lg sm:leading-8"
              rows={1}
              style={{
                minHeight: '56px',
                maxHeight: '140px',
              }}
            />
            {!isListening && (
              <button
                onClick={onSend}
                disabled={!input.trim() || isLoading || isTranscribing}
                className="mb-1 flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300 shadow-lg shadow-slate-900/15"
                aria-label="Send message"
              >
                {isLoading || isTranscribing ? (
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
            {statusText}
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
