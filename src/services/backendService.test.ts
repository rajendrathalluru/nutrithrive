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
