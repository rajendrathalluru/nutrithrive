import { BackendService } from './backendService';
import { buildConversationHistory } from '../utils/conversationHistory';

const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; });

test('preserves source annotations from the API through same-chat recipe references', async () => {
  const notes = '*Use another herb.\n**Use canned beans.';
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ source_documents: [{
      name: 'Bowl', recipe_id: 'bowl-1', source: 'database_exact',
      ingredients: ['Herbs*', 'Beans**'], instructions: ['Mix and serve.'],
      source_notes: notes, unresolved_footnotes: ['***'],
      total_time: 'Total time: 4 minutes',
      related_recipes: [{ recipe_id: 'salad-1', name: 'Bean Salad', recipe_link: 'https://recipes.heart.org/en/recipes/example', source_name: 'AHA' }],
    }] }),
  });
  const { recipes } = await BackendService.getInstance().searchRecipes('Show recipes');
  expect(recipes[0].sourceNotes).toBe(notes);
  expect(recipes[0].ingredients).toEqual(['Herbs*', 'Beans**']);
  expect(recipes[0].relatedRecipes?.[0].title).toBe('Bean Salad');
  const history = buildConversationHistory([{ id: 'message-1', role: 'assistant', content: 'A bowl.', timestamp: new Date(), recipes }]);
  expect(history[0].recipes?.[0]).toMatchObject({
    source_notes: notes, unresolved_footnotes: ['***'], total_time: 'Total time: 4 minutes',
    related_recipes: [{ name: 'Bean Salad', recipe_id: 'salad-1', recipe_link: 'https://recipes.heart.org/en/recipes/example' }],
  });
});

test('sends clarification state on the next conversational API request', async () => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ source_documents: [], response: 'Updated recipe' }) });
  const context = { version: 1, query_type: 'recipe_adaptation', operation: 'texture',
    request: 'Change the texture', selected_recipe_ids: ['millet-1'], waiting_for: 'texture' };
  const history = buildConversationHistory([{
    id: 'clarification', role: 'assistant', content: 'What texture would you like?', timestamp: new Date(),
    backendData: { intent_analysis: { recipe_context: context } },
  }]);
  await BackendService.getInstance().searchRecipes('Softer and creamier', history);
  const body = JSON.parse((global.fetch as jest.Mock).mock.calls[0][1].body);
  expect(body.conversation_history[0].recipe_context).toEqual(context);
  expect(body.query).toBe('Softer and creamier');
});
