import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import NutriThriveChatbot from './NutriThriveChatbot';
import { BackendService } from '../services/backendService';
import { Recipe } from '../types';

jest.mock('../services/backendService', () => {
  const service = {
    getHealth: jest.fn(),
    searchRecipes: jest.fn(),
    createRealtimeSession: jest.fn(),
    getBaseUrl: () => 'http://localhost:8000',
  };
  return { BackendService: { getInstance: () => service } };
});

const backendService = BackendService.getInstance();
const getHealth = backendService.getHealth as jest.Mock;
const searchRecipes = backendService.searchRecipes as jest.Mock;
const healthy = { status: 'healthy', message: 'Service is running', model_loaded: true, recipes_count: 10 };
const recipe: Recipe = {
  id: 'soup-1', title: 'Bean Soup', description: 'A warming soup.', type: 'Main Dish',
  calories: 300, tags: ['Vegetarian'], aicrVerified: false, source: 'database_exact',
  sourceName: 'AHA', sourceUrl: 'https://recipes.heart.org/en/recipes/spinach-bean-soup',
  ingredients: ['1 can beans', 'Garnishes:', '1 tsp dried parsley'],
  instructions: ['Warm the beans and add parsley.'], helpfulTips: ['Use low-sodium beans.'],
  storageGuidance: 'Refrigerate leftovers.', ingredientAdaptations: ['Try a different bean.'],
};

let isDesktop = true;

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: query.includes('min-width') ? isDesktop : !isDesktop,
      media: query, addEventListener: jest.fn(), removeEventListener: jest.fn(),
    }),
  });
  Object.defineProperty(window, 'ResizeObserver', {
    writable: true,
    value: class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  });
  HTMLElement.prototype.scrollTo = jest.fn();
});

beforeEach(() => {
  jest.clearAllMocks();
  isDesktop = true;
  getHealth.mockResolvedValue(healthy);
  searchRecipes.mockResolvedValue({ recipes: [recipe], backendData: { response: 'Here is a bean soup.' } });
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: undefined });
  Object.defineProperty(window, 'RTCPeerConnection', { configurable: true, value: undefined });
});

const readyChat = async () => {
  render(<NutriThriveChatbot />);
  await screen.findByText('Connected');
};

const send = (query: string) => {
  fireEvent.change(screen.getByRole('textbox', { name: 'Message' }), { target: { value: query } });
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
};

test('sends the unchanged prompt and preserves structured recipe context in follow-ups', async () => {
  await readyChat();
  send('Show vegetarian soups');
  await screen.findByText('Here is a bean soup.');
  expect(searchRecipes).toHaveBeenNthCalledWith(1, 'Show vegetarian soups', [
    expect.objectContaining({ role: 'assistant', content: expect.stringContaining('personalized recipes') }),
  ]);
  expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('');
  expect(screen.getByRole('link', { name: 'Source: AHA' })).toHaveAttribute('href', recipe.sourceUrl);
  fireEvent.click(screen.getByRole('button', { name: 'View Full Recipe' }));
  expect(screen.getByRole('list', { name: 'Garnishes' })).toHaveTextContent('1 tsp dried parsley');
  expect(screen.getByText('Use low-sodium beans.')).toBeInTheDocument();
  expect(screen.getByText('Refrigerate leftovers.')).toBeInTheDocument();
  expect(screen.getByText('Try a different bean.')).toBeInTheDocument();
  expect(screen.getByText(recipe.instructions[0])).toBeInTheDocument();

  send('more recipes');
  await waitFor(() => expect(searchRecipes).toHaveBeenCalledTimes(2));
  const [query, history] = searchRecipes.mock.calls[1];
  expect(query).toBe('more recipes');
  expect(history).toHaveLength(3);
  expect(history[1]).toEqual({ role: 'user', content: 'Show vegetarian soups' });
  expect(history[2]).toMatchObject({
    role: 'assistant',
    recipes: [{ recipe_id: 'soup-1', name: 'Bean Soup', recipe_link: recipe.sourceUrl, ingredients: recipe.ingredients }],
  });
  expect(history[2].content).toContain('Previously shown recipes: Bean Soup');
  await waitFor(() => expect(screen.queryByText('Searching for recipes...')).not.toBeInTheDocument());
});

test.each(['AHA', 'AICR', 'ACS'])('keeps the database source link for %s', async sourceName => {
  searchRecipes.mockResolvedValue({ recipes: [{ ...recipe, sourceName }], backendData: { response: 'Found a recipe.' } });
  await readyChat();
  send('Find a soup');
  const link = await screen.findByRole('link', { name: `Source: ${sourceName}` });
  expect(link).toHaveAttribute('href', recipe.sourceUrl);
  expect(link).toHaveAttribute('target', '_blank');
  expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  expect(screen.queryByText('AI Generated')).not.toBeInTheDocument();
});

test('preserves AI labeling without presenting database attribution', async () => {
  searchRecipes.mockResolvedValue({ recipes: [{ ...recipe, source: 'llm_generated' }], backendData: { response: 'An original recipe.' } });
  await readyChat();
  send('Create a soup');
  expect(await screen.findByText('AI Generated')).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: /Source:/ })).not.toBeInTheDocument();
});

test('keeps chats independent, including responses arriving after a chat switch', async () => {
  let resolveSearch!: (value: unknown) => void;
  searchRecipes.mockImplementationOnce(() => new Promise(resolve => { resolveSearch = resolve; }));
  await readyChat();
  send('First conversation');
  expect(screen.getByText('Searching for recipes...')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'New Chat' }));
  await act(async () => { resolveSearch({ recipes: [recipe], backendData: { response: 'First chat answer.' } }); });
  expect(screen.queryByText('First chat answer.')).not.toBeInTheDocument();
  expect(screen.queryByText('Bean Soup')).not.toBeInTheDocument();
  searchRecipes.mockResolvedValueOnce({ recipes: [], backendData: { response: 'Second chat answer.' } });
  send('Second conversation');
  await screen.findByText('Second chat answer.');
  expect(searchRecipes.mock.calls[1][1]).toHaveLength(1);
  expect(JSON.stringify(searchRecipes.mock.calls[1][1])).not.toContain('First conversation');
  fireEvent.click(screen.getByRole('button', { name: /First conversation\.\.\./ }));
  expect(await screen.findByText('First chat answer.')).toBeInTheDocument();
  expect(screen.getByText('Bean Soup')).toBeInTheDocument();
  expect(screen.queryByText('Second chat answer.')).not.toBeInTheDocument();
});

test('blocks sending while warming up and enables it after the existing health poll', async () => {
  jest.useFakeTimers();
  try {
    getHealth.mockResolvedValueOnce({ ...healthy, status: 'starting', model_loaded: false });
    await act(async () => { render(<NutriThriveChatbot />); });
    expect(screen.getByText('Recipe engine is warming up')).toBeInTheDocument();
    send('A simple meal');
    expect(searchRecipes).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled();
    await act(async () => { jest.advanceTimersByTime(5000); });
    expect(screen.getByText('Connected')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send message' })).toBeEnabled();
  } finally {
    jest.useRealTimers();
  }
});

test('keeps backend safety responses and crisis actions intact', async () => {
  searchRecipes.mockResolvedValue({ recipes: [], backendData: { response: 'Please reach out for immediate support.', safety_redirect: true } });
  await readyChat();
  send('A safety test prompt');
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('Please reach out for immediate support.');
  expect(within(alert).getByRole('link', { name: 'Call 988' })).toHaveAttribute('href', 'tel:988');
  expect(within(alert).getByRole('link', { name: 'Text 988' })).toHaveAttribute('href', 'sms:988');
  expect(within(alert).getByRole('link', { name: 'International help' })).toHaveAttribute('href', 'https://findahelpline.com');
  expect(screen.queryByRole('button', { name: 'View Full Recipe' })).not.toBeInTheDocument();
});

test('shows backend errors and prevents another send while offline', async () => {
  searchRecipes.mockRejectedValueOnce(new Error('Connection unavailable'));
  await readyChat();
  send('Find a recipe');
  expect(await screen.findByText(/Connection unavailable/)).toBeInTheDocument();
  expect(screen.getByText('Offline')).toBeInTheDocument();
  send('Try again');
  expect(searchRecipes).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled();
});

test('preserves Enter sending and Shift+Enter for multiline drafts', async () => {
  await readyChat();
  const input = screen.getByRole('textbox', { name: 'Message' });
  fireEvent.change(input, { target: { value: 'A simple meal' } });
  fireEvent.keyPress(input, { key: 'Enter', code: 'Enter', charCode: 13, shiftKey: true });
  expect(searchRecipes).not.toHaveBeenCalled();
  fireEvent.keyPress(input, { key: 'Enter', code: 'Enter', charCode: 13 });
  await screen.findByText('Here is a bean soup.');
  expect(searchRecipes).toHaveBeenCalledTimes(1);
});

test('suggestion cards fill and focus the draft without sending a request', async () => {
  await readyChat();
  fireEvent.click(screen.getByRole('button', { name: /Quick & easy/ }));
  expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('Show recipes that take 30 minutes or less.');
  expect(screen.getByRole('textbox', { name: 'Message' })).toHaveFocus();
  expect(searchRecipes).not.toHaveBeenCalled();
});

test('keeps search analysis available in a disclosure', async () => {
  searchRecipes.mockResolvedValue({ recipes: [], backendData: {
    response: 'Matching your requirements.',
    intent_analysis: { search_strategy: { primary_focus: 'Easy microwave meals' }, constraints: { equipment_only: ['microwave'] } },
  } });
  await readyChat();
  send('Microwave meals');
  const summary = await screen.findByText('Search Analysis');
  fireEvent.click(summary);
  expect(summary.closest('details')).toHaveAttribute('open');
  expect(screen.getByText('Easy microwave meals')).toBeVisible();
  expect(screen.getByText('Microwave-only recipes prioritized')).toBeVisible();
});

test('mobile navigation closes after selecting a chat and with Escape', async () => {
  isDesktop = false;
  await readyChat();
  expect(screen.queryByRole('navigation', { name: 'Recent conversations' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Toggle conversations' }));
  expect(screen.getByRole('navigation', { name: 'Recent conversations' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /New Chat 1 messages/ }));
  expect(screen.queryByRole('navigation', { name: 'Recent conversations' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Toggle conversations' }));
  fireEvent.keyDown(window, { key: 'Escape' });
  expect(screen.queryByRole('navigation', { name: 'Recent conversations' })).not.toBeInTheDocument();
});

test('the existing back-to-home callback remains available', async () => {
  const onBackToHome = jest.fn();
  render(<NutriThriveChatbot onBackToHome={onBackToHome} />);
  await screen.findByText('Connected');
  fireEvent.click(screen.getByRole('button', { name: /Your workspace/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Back to Home' }));
  expect(onBackToHome).toHaveBeenCalledTimes(1);
});

test('voice input still uses microphone permissions and surfaces permission errors', async () => {
  const getUserMedia = jest.fn().mockRejectedValue(new Error('Microphone permission denied'));
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });
  Object.defineProperty(window, 'RTCPeerConnection', { configurable: true, value: jest.fn() });
  await readyChat();
  fireEvent.click(screen.getByRole('button', { name: 'Start voice input' }));
  expect(await screen.findByText('Microphone permission denied')).toBeInTheDocument();
  expect(getUserMedia).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Start voice input' })).toBeEnabled();
  expect(searchRecipes).not.toHaveBeenCalled();
});

test('live voice transcription fills the same draft and submits through the existing recipe API', async () => {
  const microphone = { enabled: false, stop: jest.fn() };
  const stream = { getAudioTracks: () => [microphone], getTracks: () => [microphone] };
  const getUserMedia = jest.fn().mockResolvedValue(stream);
  const channel = Object.assign(new EventTarget(), { readyState: 'open', send: jest.fn(), close: jest.fn() });
  const peer = {
    createDataChannel: jest.fn().mockReturnValue(channel), addTrack: jest.fn(),
    createOffer: jest.fn().mockResolvedValue({ type: 'offer', sdp: 'test-offer' }),
    setLocalDescription: jest.fn().mockResolvedValue(undefined),
    localDescription: { sdp: 'test-offer' },
    setRemoteDescription: jest.fn().mockResolvedValue(undefined), close: jest.fn(),
  };
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });
  Object.defineProperty(window, 'RTCPeerConnection', { configurable: true, value: jest.fn(() => peer) });
  (backendService.createRealtimeSession as jest.Mock).mockResolvedValue('test-answer');
  const { unmount } = render(<NutriThriveChatbot />);
  await screen.findByText('Connected');
  fireEvent.change(screen.getByRole('textbox', { name: 'Message' }), { target: { value: 'Please suggest' } });
  fireEvent.click(screen.getByRole('button', { name: 'Start voice input' }));
  await screen.findByRole('button', { name: 'Stop voice input' });
  expect(microphone.enabled).toBe(true);
  expect(backendService.createRealtimeSession).toHaveBeenCalledWith('test-offer');
  expect(peer.setRemoteDescription).toHaveBeenCalledWith({ type: 'answer', sdp: 'test-answer' });
  act(() => {
    channel.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({
      type: 'conversation.item.input_audio_transcription.delta', item_id: 'voice-1', delta: 'vegetarian soup',
    }) }));
  });
  expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('Please suggest vegetarian soup');
  expect(screen.queryByRole('button', { name: 'Send message' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Stop voice input' }));
  expect(microphone.enabled).toBe(false);
  expect(channel.send).toHaveBeenCalledWith(JSON.stringify({ type: 'input_audio_buffer.commit' }));
  expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled();
  act(() => {
    channel.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({
      type: 'conversation.item.input_audio_transcription.completed', item_id: 'voice-1', transcript: 'vegetarian soups',
    }) }));
  });
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  await screen.findByText('Here is a bean soup.');
  expect(searchRecipes).toHaveBeenCalledWith('Please suggest vegetarian soups', expect.any(Array));
  unmount();
  expect(microphone.stop).toHaveBeenCalled();
  expect(channel.close).toHaveBeenCalledTimes(1);
  expect(peer.close).toHaveBeenCalledTimes(1);
});
