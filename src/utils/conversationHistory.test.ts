import { Message, Recipe } from '../types';
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
