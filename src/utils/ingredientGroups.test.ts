import { groupIngredients } from './ingredientGroups';

test('groups sauce and garnishes while retaining main ingredients and order', () => {
  const ingredients = ['1 cup rice', 'Teriyaki Sauce:', '1 tbsp tamari', '1 tsp honey', 'Garnishes:', '1 tsp sesame seeds'];
  expect(groupIngredients(ingredients)).toEqual([
    { kind: 'ingredient', text: '1 cup rice' },
    { kind: 'section', heading: 'Teriyaki Sauce:', ingredients: ['1 tbsp tamari', '1 tsp honey'] },
    { kind: 'section', heading: 'Garnishes:', ingredients: ['1 tsp sesame seeds'] },
  ]);
  expect(ingredients).toEqual(['1 cup rice', 'Teriyaki Sauce:', '1 tbsp tamari', '1 tsp honey', 'Garnishes:', '1 tsp sesame seeds']);
});

test('supports multiline ingredients and common headings without colons', () => {
  expect(groupIngredients(['**For the sauce:**\n- 1 tbsp olive oil\n- 2 tbsp vinegar', 'Garnish (optional)', '• Parsley'])).toEqual([
    { kind: 'section', heading: 'For the sauce:', ingredients: ['1 tbsp olive oil', '2 tbsp vinegar'] },
    { kind: 'section', heading: 'Garnish (optional)', ingredients: ['Parsley'] },
  ]);
});

test('keeps ordinary ingredients and inline labels as flat bullets', () => {
  const ingredients = ['Soy sauce', '1 cup tomato sauce', 'Optional: chopped parsley', 'Salt, to taste'];
  expect(groupIngredients(ingredients)).toEqual(ingredients.map(text => ({ kind: 'ingredient', text })));
});

test('preserves headings with no children without creating empty nested lists', () => {
  expect(groupIngredients(['', 'Sauce:', 'Garnishes:', ' '])).toEqual([
    { kind: 'ingredient', text: 'Sauce:' },
    { kind: 'ingredient', text: 'Garnishes:' },
  ]);
  expect(groupIngredients([])).toEqual([]);
});
