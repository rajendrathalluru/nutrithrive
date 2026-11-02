export async function readRecipeStream(
  response: Response,
  onProgress: (message: string) => void
): Promise<any> {
  if (!response.body) throw new Error('Recipe progress connection is unavailable. Please try again.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let separator: RegExpExecArray | null;
      while ((separator = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        const lines = frame.split(/\r?\n/);
        const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
        const dataLines = lines.filter(line => line.startsWith('data:'));
        if (!dataLines.length) continue;
        const data = JSON.parse(dataLines.map(line => line.slice(5).trimStart()).join('\n'));
        if (event === 'progress' && typeof data.message === 'string') onProgress(data.message);
        if (event === 'error') throw new Error(data.message || 'Recipe request failed. Please try again.');
        if (event === 'result') {
          if (typeof data.response !== 'string' || !Array.isArray(data.source_documents)) {
            throw new Error('The recipe service returned an incomplete response. Please try again.');
          }
          return data;
        }
      }
      if (done) throw new Error('The connection ended before the recipe checks finished. Please try again.');
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
