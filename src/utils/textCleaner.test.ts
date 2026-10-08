import { cleanBackendText, formatIngredients, formatInstructions } from './textCleaner';

test('removes actual emphasis without consuming ingredient footnotes', () => {
  expect(cleanBackendText('**Ingredients:**')).toBe('Ingredients:');
  expect(cleanBackendText('*Sauce*')).toBe('Sauce');
  expect(formatIngredients(['1 tbsp za’atar*', '1 cup beans* or lentils**', '**Topping:**']))
    .toEqual(['1 tbsp za’atar*', '1 cup beans* or lentils**', 'Topping:']);
  expect(cleanBackendText('*First note\n**Second note')).toBe('*First note\n**Second note');
});

test('keeps instruction footnotes while removing numbering and list prefixes', () => {
  expect(formatInstructions(['1. Mix and serve.*', '2) Chill.', '- Top with herbs.']))
    .toEqual(['Mix and serve.*', 'Chill.', 'Top with herbs.']);
});
