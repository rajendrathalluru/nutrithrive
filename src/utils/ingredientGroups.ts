import { cleanBackendText } from './textCleaner';

export type IngredientEntry =
  | { kind: 'ingredient'; text: string }
  | { kind: 'section'; heading: string; ingredients: string[] };

const isSectionHeading = (text: string): boolean => {
  if (/^(?:for (?:the )?)?(?:sauce|garnish(?:es)?|dressing|marinade|toppings?|filling|crust|salad|batter|dough)(?: \(optional\))?:?$/i.test(text)) {
    return true;
  }
  return text.endsWith(':') && text.length <= 80 && !/[\d]/.test(text);
};

export const groupIngredients = (ingredients: string[]): IngredientEntry[] => {
  const entries: IngredientEntry[] = [];
  let section: Extract<IngredientEntry, { kind: 'section' }> | undefined;

  ingredients.forEach(ingredient => {
    ingredient.split(/\r?\n/).forEach(line => {
      const text = cleanBackendText(line.trim().replace(/^[-*•]\s+/, ''));
      if (!text) return;

      if (isSectionHeading(text)) {
        section = { kind: 'section', heading: text, ingredients: [] };
        entries.push(section);
      } else if (section) {
        section.ingredients.push(text);
      } else {
        entries.push({ kind: 'ingredient', text });
      }
    });
  });

  return entries.map(entry => entry.kind === 'section' && entry.ingredients.length === 0
    ? { kind: 'ingredient', text: entry.heading }
    : entry);
};
