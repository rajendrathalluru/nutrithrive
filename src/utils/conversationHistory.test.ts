import { Message, Recipe, RecipeConversationContext } from '../types';
import { buildConversationHistory } from './conversationHistory';

const recipe: Recipe = {
  id: 'soup-1', title: 'Spinach Soup', description: 'Mild soup', type: 'Soup',
  calories: 139, ingredients: ['Spinach', 'Vegetable broth'], instructions: ['Simmer the soup.'],
  tags: [], aicrVerified: false, source: 'database_exact', sourceName: 'AHA',
  sourceUrl: 'https://recipes.heart.org/en/recipes/example'
};

test('includes full recipe references and excludes loading messages', () => {
  const messages: Message[] = [
    { id: '1', role: 'user', content: 'Mild meals', timestamp: new Date() },
    { id: '2', role: 'assistant', content: 'Try this soup.', recipes: [recipe], timestamp: new Date() },
    { id: '3', role: 'assistant', content: '', isLoading: true, timestamp: new Date() }
  ];
  const history = buildConversationHistory(messages);
  expect(history).toHaveLength(2);
  expect(history[1].recipes?.[0]).toMatchObject({
    recipe_id: 'soup-1', name: 'Spinach Soup', ingredients: recipe.ingredients,
    instructions: recipe.instructions, source_name: 'AHA', database_record_found: true
  });
  expect(history[1].content).toContain('Previously shown recipes: Spinach Soup');
  expect(messages[1].content).toBe('Try this soup.');
});

test('each chat supplies only its own messages and recipe references', () => {
  const firstChat: Message[] = [{ id: '1', role: 'assistant', content: 'Soup', recipes: [recipe], timestamp: new Date() }];
  const secondChat: Message[] = [{ id: '2', role: 'user', content: 'Chinese dinner', timestamp: new Date() }];
  expect(buildConversationHistory(firstChat)[0].recipes).toHaveLength(1);
  expect(buildConversationHistory(secondChat)).toEqual([{ role: 'user', content: 'Chinese dinner' }]);
  expect(buildConversationHistory([])).toEqual([]);
});

test('preserves backend request boundaries without inventing them for older messages', () => {
  const messages: Message[] = [
    { id: '1', role: 'assistant', content: 'Old recipe', timestamp: new Date() },
    { id: '2', role: 'assistant', content: 'New bowl', timestamp: new Date(), recipes: [recipe],
      backendData: { intent_analysis: { context_action: 'new_request' } } },
    { id: '3', role: 'assistant', content: 'More bowls', timestamp: new Date(),
      backendData: { intent_analysis: { context_action: 'continue_request' } } },
  ];
  const history = buildConversationHistory(messages);
  expect(history[0].context_action).toBeUndefined();
  expect(history[1].context_action).toBe('new_request');
  expect(history[1].recipes?.[0].ingredients).toEqual(recipe.ingredients);
  expect(history[2].context_action).toBe('continue_request');
});

test('carries pending recipe clarification even when the assistant returns no cards', () => {
  const context: RecipeConversationContext = {
    version: 1, query_type: 'recipe_adaptation', operation: 'texture',
    selected_recipe_ids: ['soup-1'], request: 'Can you change the texture?', waiting_for: 'texture',
  };
  const messages: Message[] = [
    { id: '1', role: 'assistant', content: 'Soup', timestamp: new Date(), recipes: [recipe] },
    { id: '2', role: 'user', content: 'Can you change the texture?', timestamp: new Date() },
    { id: '3', role: 'assistant', content: 'What texture would you like?', timestamp: new Date(),
      backendData: { intent_analysis: { context_action: 'continue_request', recipe_context: context } } },
  ];
  const history = buildConversationHistory(messages);
  expect(history[2].recipe_context).toEqual(context);
  expect(history[2].recipes).toBeUndefined();
  expect(history[0].recipes?.[0].instructions).toEqual(recipe.instructions);
  history[2].recipe_context?.selected_recipe_ids.push('do-not-mutate-original');
  expect(context.selected_recipe_ids).toEqual(['soup-1']);
  expect(buildConversationHistory([{ id: '4', role: 'user', content: 'Breakfast', timestamp: new Date() }]))
    .toEqual([{ role: 'user', content: 'Breakfast' }]);
});

test('keeps the new adapted recipe selected after a question without cards', () => {
  const context: RecipeConversationContext = {
    version: 1, query_type: 'recipe_question', operation: 'question',
    selected_recipe_ids: ['creamy-soup'], request: 'Can I freeze it?',
  };
  const history = buildConversationHistory([
    { id: '1', role: 'assistant', content: 'Updated soup', timestamp: new Date(), recipes: [{ ...recipe, id: 'creamy-soup', source: 'llm_generated' }] },
    { id: '2', role: 'assistant', content: 'Check the recipe storage instructions.', timestamp: new Date(),
      backendData: { intent_analysis: { recipe_context: context } } },
  ]);
  expect(history[0].recipes?.[0].generated_by_llm).toBe(true);
  expect(history[1].recipe_context?.selected_recipe_ids).toEqual(['creamy-soup']);
});
