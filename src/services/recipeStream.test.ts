import { TextDecoder, TextEncoder } from 'util';
import { readRecipeStream } from './recipeStream';
import { BackendService } from './backendService';

const originalFetch = global.fetch;
beforeAll(() => { Object.defineProperty(global, 'TextDecoder', { value: TextDecoder, configurable: true }); });
afterEach(() => { global.fetch = originalFetch; });

function streamResponse(text: string, bytewise = false) {
  const bytes = new TextEncoder().encode(text);
  const chunks = bytewise ? Array.from(bytes, value => new Uint8Array([value])) : [bytes];
  const reader = {
    read: jest.fn(async () => chunks.length ? { value: chunks.shift(), done: false } : { done: true }),
    cancel: jest.fn(async () => undefined),
    releaseLock: jest.fn(),
  };
  return {
    reader,
    response: { ok: true, headers: { get: () => 'text/event-stream; charset=utf-8' },
      body: { getReader: () => reader } } as unknown as Response,
  };
}

const final = { response: 'Checked sautéed beans', source_documents: [{ name: 'Bean Bowl', ingredients: ['Beans'], instructions: ['Heat.'] }] };

test('decodes fragmented UTF-8 and CRLF, ignores keepalives, and returns only a terminal result', async () => {
  const { response, reader } = streamResponse(
    ': keepalive\r\n\r\nevent: progress\r\ndata: {"message":"Checking recipes…"}\r\n\r\n'
    + `event: result\ndata: ${JSON.stringify(final)}\n\n`, true
  );
  const progress = jest.fn();
  expect(await readRecipeStream(response, progress)).toEqual(final);
  expect(progress).toHaveBeenCalledTimes(1);
  expect(progress).toHaveBeenCalledWith('Checking recipes…');
  expect(reader.cancel).toHaveBeenCalled();
  expect(reader.releaseLock).toHaveBeenCalled();
});

test.each([
  ['event: progress\ndata: {"message":"Checking recipes…"}\n\n', 'before the recipe checks finished'],
  ['event: error\ndata: {"message":"Verification unavailable"}\n\n', 'Verification unavailable'],
  ['event: result\ndata: {"response":"Incomplete"}\n\n', 'incomplete response'],
])('does not treat incomplete/error streams as recipe results', async (text, expected) => {
  const { response, reader } = streamResponse(text);
  await expect(readRecipeStream(response, jest.fn())).rejects.toThrow(expected);
  expect(reader.releaseLock).toHaveBeenCalled();
});

test('service opts into streaming and preserves unchanged query and history', async () => {
  const { response } = streamResponse(`event: progress\ndata: {"message":"Checking recipes…"}\n\nevent: result\ndata: ${JSON.stringify(final)}\n\n`);
  global.fetch = jest.fn().mockResolvedValue(response);
  const history = [{ role: 'user' as const, content: 'Vegetarian meals' }];
  const progress = jest.fn();
  const output = await BackendService.getInstance().searchRecipes('More recipes', history, progress);
  const options = (global.fetch as jest.Mock).mock.calls[0][1];
  expect(options.headers.Accept).toBe('text/event-stream');
  expect(options.credentials).toBe('include');
  expect(JSON.parse(options.body)).toEqual({ query: 'More recipes', mode: 'auto', conversation_history: history });
  expect(output.recipes[0].title).toBe('Bean Bowl');
  expect(output.backendData).toEqual(final);
  expect(global.fetch).toHaveBeenCalledTimes(1);
});

test('old backends and safety redirects can return JSON without replaying the request', async () => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, headers: { get: () => 'application/json' }, json: async () => final });
  const output = await BackendService.getInstance().searchRecipes('Dinner', [], jest.fn());
  expect(output.backendData).toEqual(final);
  expect(global.fetch).toHaveBeenCalledTimes(1);
});

test('stream interruption never triggers a second generation request', async () => {
  const { response } = streamResponse('event: progress\ndata: {"message":"Checking recipes…"}\n\n');
  global.fetch = jest.fn().mockResolvedValue(response);
  await expect(BackendService.getInstance().searchRecipes('Dinner', [], jest.fn())).rejects.toThrow('before the recipe checks finished');
  expect(global.fetch).toHaveBeenCalledTimes(1);
});
