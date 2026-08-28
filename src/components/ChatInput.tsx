import React, { useEffect, useRef, useState } from 'react';
import { Send, Loader2, CornerDownLeft, Mic, Square } from 'lucide-react';
import { BackendService } from '../services/backendService';

interface ChatInputProps {
  input: string;
  isLoading: boolean;
  backendReady: boolean;
  backendStatusMessage: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onKeyPress: (e: React.KeyboardEvent) => void;
}

const backendService = BackendService.getInstance();

const ChatInput: React.FC<ChatInputProps> = ({
  input,
  isLoading,
  backendReady,
  backendStatusMessage,
  onInputChange,
  onSend
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const microphoneTrackRef = useRef<MediaStreamTrack | null>(null);
  const connectionPromiseRef = useRef<Promise<void> | null>(null);
  const voiceBaseInputRef = useRef('');
  const transcriptByItemRef = useRef<Map<string, string>>(new Map());
  const activeTranscriptItemIdRef = useRef<string | null>(null);
  const awaitingFinalTranscriptRef = useRef(false);

  const [isListening, setIsListening] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [isConnectingVoice, setIsConnectingVoice] = useState(false);
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
    const isSupported =
      typeof window !== 'undefined'
      && typeof navigator !== 'undefined'
      && !!navigator.mediaDevices?.getUserMedia
      && typeof RTCPeerConnection !== 'undefined';

    setVoiceSupported(isSupported);
  }, []);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 640px)');
    const updatePlaceholderMode = () => setIsCompactPlaceholder(mediaQuery.matches);

    updatePlaceholderMode();
    mediaQuery.addEventListener('change', updatePlaceholderMode);

    return () => {
      mediaQuery.removeEventListener('change', updatePlaceholderMode);
    };
  }, []);

  const cleanupRealtimeConnection = () => {
    dataChannelRef.current?.close();
    dataChannelRef.current = null;
    peerConnectionRef.current?.close();
    peerConnectionRef.current = null;
    connectionPromiseRef.current = null;
  };

  const cleanupMicrophone = () => {
    microphoneTrackRef.current?.stop();
    microphoneTrackRef.current = null;
    localStreamRef.current?.getTracks().forEach((track) => track.stop());
    localStreamRef.current = null;
  };

  useEffect(() => () => {
    cleanupRealtimeConnection();
    cleanupMicrophone();
  }, []);

  const applyTranscript = (transcript: string) => {
    const nextValue = [voiceBaseInputRef.current, transcript.trim()].filter(Boolean).join(' ').trim();
    onInputChange(nextValue);
  };

  const handleRealtimeEvent = (event: MessageEvent) => {
    try {
      const payload = JSON.parse(event.data);
      const eventType = payload?.type;

      if (eventType === 'conversation.item.input_audio_transcription.delta') {
        const itemId = typeof payload.item_id === 'string' ? payload.item_id : null;
        const delta = typeof payload.delta === 'string' ? payload.delta : '';

        if (!itemId || !delta) {
          return;
        }

        activeTranscriptItemIdRef.current = itemId;
        const previousText = transcriptByItemRef.current.get(itemId) || '';
        const nextText = `${previousText}${delta}`;
        transcriptByItemRef.current.set(itemId, nextText);
        applyTranscript(nextText);
        setIsTranscribing(false);
        return;
      }

      if (eventType === 'conversation.item.input_audio_transcription.completed') {
        const itemId = typeof payload.item_id === 'string' ? payload.item_id : null;
        const transcript = typeof payload.transcript === 'string'
          ? payload.transcript
          : itemId
            ? transcriptByItemRef.current.get(itemId) || ''
            : '';

        if (itemId) {
          transcriptByItemRef.current.set(itemId, transcript);
          activeTranscriptItemIdRef.current = itemId;
        }

        applyTranscript(transcript);
        awaitingFinalTranscriptRef.current = false;
        setIsTranscribing(false);
        return;
      }

      if (eventType === 'error') {
        const message = typeof payload?.error?.message === 'string'
          ? payload.error.message
          : 'Live voice transcription is temporarily unavailable.';
        setVoiceError(message);
        setIsListening(false);
        setIsTranscribing(false);
        awaitingFinalTranscriptRef.current = false;
        return;
      }
    } catch {
      setVoiceError('Received an invalid live voice event.');
      setIsListening(false);
      setIsTranscribing(false);
      awaitingFinalTranscriptRef.current = false;
    }
  };

  const ensureMicrophone = async () => {
    if (microphoneTrackRef.current && localStreamRef.current) {
      return;
    }

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const [track] = stream.getAudioTracks();

    if (!track) {
      throw new Error('Microphone access was unavailable.');
    }

    track.enabled = false;
    localStreamRef.current = stream;
    microphoneTrackRef.current = track;
  };

  const waitForDataChannelOpen = (channel: RTCDataChannel) => new Promise<void>((resolve, reject) => {
    if (channel.readyState === 'open') {
      resolve();
      return;
    }

    const handleOpen = () => {
      channel.removeEventListener('open', handleOpen);
      channel.removeEventListener('error', handleError);
      resolve();
    };

    const handleError = () => {
      channel.removeEventListener('open', handleOpen);
      channel.removeEventListener('error', handleError);
      reject(new Error('Unable to open live voice data channel.'));
    };

    channel.addEventListener('open', handleOpen);
    channel.addEventListener('error', handleError);
  });

  const ensureRealtimeConnection = async () => {
    const existingPeer = peerConnectionRef.current;
    const existingChannel = dataChannelRef.current;

    if (
      existingPeer
      && existingChannel
      && existingPeer.connectionState !== 'closed'
      && existingChannel.readyState === 'open'
    ) {
      return;
    }

    if (connectionPromiseRef.current) {
      return connectionPromiseRef.current;
    }

    connectionPromiseRef.current = (async () => {
      setIsConnectingVoice(true);
      await ensureMicrophone();

      const peerConnection = new RTCPeerConnection();
      const dataChannel = peerConnection.createDataChannel('oai-events');

      peerConnectionRef.current = peerConnection;
      dataChannelRef.current = dataChannel;

      dataChannel.addEventListener('message', handleRealtimeEvent);
      dataChannel.addEventListener('close', () => {
        dataChannelRef.current = null;
      });

      peerConnection.addTrack(microphoneTrackRef.current as MediaStreamTrack, localStreamRef.current as MediaStream);

      const offer = await peerConnection.createOffer();
      await peerConnection.setLocalDescription(offer);
      const localSdp = peerConnection.localDescription?.sdp;

      if (!localSdp) {
        throw new Error('Unable to create live voice session offer.');
      }

      const answerSdp = await backendService.createRealtimeSession(localSdp);
      await peerConnection.setRemoteDescription({
        type: 'answer',
        sdp: answerSdp,
      });

      await waitForDataChannelOpen(dataChannel);

      dataChannel.send(JSON.stringify({
        type: 'session.update',
        session: {
          type: 'transcription',
          audio: {
            input: {
              transcription: {
                model: 'gpt-realtime-whisper',
                language: 'en',
                delay: 'minimal',
              },
              turn_detection: null,
            },
          },
        },
      }));
    })();

    try {
      await connectionPromiseRef.current;
    } finally {
      setIsConnectingVoice(false);
      connectionPromiseRef.current = null;
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!isListening && !isTranscribing && !isConnectingVoice && backendReady) {
        onSend();
      }
    }
  };

  const startVoiceInput = async () => {
    if (!backendReady) {
      setVoiceError(backendStatusMessage);
      return;
    }

    if (!voiceSupported || isConnectingVoice) {
      setVoiceError('Voice input is not supported in this browser.');
      return;
    }

    try {
      setVoiceError('');
      setIsTranscribing(false);
      voiceBaseInputRef.current = input.trim();
      transcriptByItemRef.current.clear();
      activeTranscriptItemIdRef.current = null;
      awaitingFinalTranscriptRef.current = false;

      await ensureRealtimeConnection();

      const track = microphoneTrackRef.current;
      if (!track) {
        throw new Error('Microphone track is unavailable.');
      }

      track.enabled = true;
      setIsListening(true);
    } catch (error) {
      const message = error instanceof Error
        ? error.message
        : 'Unable to start live voice input.';
      setVoiceError(message);
      setIsListening(false);
      setIsTranscribing(false);
      cleanupRealtimeConnection();
      cleanupMicrophone();
    }
  };

  const stopVoiceInput = () => {
    const track = microphoneTrackRef.current;
    const dataChannel = dataChannelRef.current;

    if (!track || !dataChannel || dataChannel.readyState !== 'open') {
      setIsListening(false);
      setIsTranscribing(false);
      return;
    }

    track.enabled = false;
    awaitingFinalTranscriptRef.current = true;
    setIsListening(false);
    setIsTranscribing(true);

    dataChannel.send(JSON.stringify({
      type: 'input_audio_buffer.commit',
    }));
  };

  const handleToggleVoice = () => {
    if (isListening) {
      stopVoiceInput();
      return;
    }

    void startVoiceInput();
  };

  const placeholderText = isCompactPlaceholder
    ? 'Ask for recipes or ingredients...'
    : 'Describe your dietary needs, ingredients available, or ask for recipe ideas...';

  const statusText = voiceError
    || (!backendReady
      ? backendStatusMessage
      : '')
    || (isConnectingVoice
      ? 'Connecting live voice session...'
      : isListening
        ? 'Listening live... words should appear as you speak'
        : isTranscribing
          ? 'Finalizing your voice transcript...'
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
                  disabled={!backendReady || isConnectingVoice || isTranscribing}
                  className="mb-1 flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-600 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-300"
                  aria-label="Start voice input"
                  title="Start voice input"
                >
                  {isConnectingVoice || isTranscribing ? (
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
              disabled={isConnectingVoice}
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
                disabled={!backendReady || !input.trim() || isLoading || isConnectingVoice || isTranscribing}
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
