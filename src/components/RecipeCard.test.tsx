import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import RecipeCard from './RecipeCard';
import { Recipe } from '../types';

const recipe: Recipe = {
  id: 'rice-bowl', title: 'Rice Bowl', description: 'A rice bowl.', type: 'Main Dish',
  calories: 300, tags: [], aicrVerified: false,
  ingredients: ['1 cup rice', 'Sauce:', '1 tbsp tamari', 'Garnishes:', '1 tsp sesame seeds'],
  instructions: ['Cook rice and add sauce and garnishes.'],
};

test('only shows budget details when provided by the backend', () => {
  const { rerender } = render(<RecipeCard recipe={recipe} />);
  expect(screen.queryByRole('region', { name: 'Budget estimate' })).not.toBeInTheDocument();
  rerender(<RecipeCard recipe={{ ...recipe, budgetAssessment: {
    status: 'estimated_within_budget', currency: 'USD', basis: 'recipe', estimate: '1.40',
    planning_ceiling: '1.68', observed_on: '2026-11-01',
    assumptions: ['Before tax and delivery fees.'],
    line_items: [{ ingredient: 'Dry rice', used_cost: '0.40', packages_to_buy: 1,
      purchase_cost: '4.00', source_url: 'https://example.com/rice' }],
  } }} />);
  const budget = screen.getByRole('region', { name: 'Budget estimate' });
  expect(budget).toHaveTextContent('Estimated within budget');
  expect(budget).toHaveTextContent('USD $1.40 · whole recipe');
  expect(budget).toHaveTextContent('Planning ceiling $1.68');
  expect(budget).toHaveTextContent('not a guaranteed checkout total');
  fireEvent.click(within(budget).getByText('Cost breakdown and assumptions'));
  expect(budget).toHaveTextContent('Dry rice: $0.40 used; 1 package(s) to buy, $4.00.');
  expect(within(budget).getByRole('link', { name: 'Price source' })).toHaveAttribute('href', 'https://example.com/rice');
});

test('does not turn an uncertain estimate into a budget claim or unsafe link', () => {
  render(<RecipeCard recipe={{ ...recipe, budgetAssessment: {
    status: 'uncertain', currency: 'USD', basis: 'shopping', issues: ['Unpriced ingredient.'],
    line_items: [{ ingredient: 'Rice', used_cost: '1.00', packages_to_buy: 1,
      purchase_cost: '4.00', source_url: 'javascript:alert(1)' }],
  } }} />);
  expect(screen.getByText('Budget not confirmed')).toBeInTheDocument();
  expect(screen.queryByText('Estimated within budget')).not.toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'Price source' })).not.toBeInTheDocument();
});

test('distinguishes already-owned food from a zero ingredient value and shows price evidence', () => {
  render(<RecipeCard recipe={{ ...recipe, budgetAssessment: {
    status: 'estimated_within_budget', currency: 'USD', basis: 'shopping', estimate: '4.00',
    line_items: [
      { ingredient: 'Salmon', used_cost: null, packages_to_buy: 0, purchase_cost: '0.00', source_url: '' },
      { ingredient: 'Rice', used_cost: '0.40', packages_to_buy: 1, purchase_cost: '4.00',
        source_url: 'https://example.com/rice', product: 'Rice, 1 kg', observed_on: '2026-11-04', region: 'Reference store' },
    ],
  } }} />);
  const budget = screen.getByRole('region', { name: 'Budget estimate' });
  expect(budget).toHaveTextContent('Salmon: consumed value unknown; 0 package(s) to buy, $0.00.');
  expect(budget).not.toHaveTextContent('$null');
  expect(budget).toHaveTextContent('Reference product: Rice, 1 kg');
  expect(budget).toHaveTextContent('Checked 2026-11-04 · Reference store');
  expect(within(budget).getAllByRole('link', { name: 'Price source' })).toHaveLength(1);
});

test('labels web-retrieved product prices without claiming live checkout or an average', () => {
  render(<RecipeCard recipe={{ ...recipe, budgetAssessment: {
    status: 'estimated_within_budget', currency: 'USD', basis: 'recipe', estimate: '0.85',
    line_items: [{ ingredient: 'Dry lentils', used_cost: '0.85', packages_to_buy: 1,
      purchase_cost: '1.92', source_url: 'https://www.walmart.com/ip/123',
      product: 'Lentils, 1 lb', price_basis: 'web_listing', observed_on: '2026-11-04' }],
  } }} />);
  const budget = screen.getByRole('region', { name: 'Budget estimate' });
  expect(budget).toHaveTextContent('Retrieved 2026-11-04');
  expect(budget).toHaveTextContent('not a live checkout quote');
  expect(budget).not.toHaveTextContent('average');
  expect(within(budget).getByRole('link', { name: 'Price source' })).toHaveAttribute('href', 'https://www.walmart.com/ip/123');
});

test.each(['database_exact', 'llm_generated'])('renders accessible nested ingredient bullets for %s', source => {
  render(<RecipeCard recipe={{ ...recipe, source }} />);
  expect(screen.queryByRole('list', { name: 'Ingredients' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'View Full Recipe' }));

  const ingredients = screen.getByRole('list', { name: 'Ingredients' });
  const sauce = within(ingredients).getByRole('list', { name: 'Sauce' });
  const garnishes = within(ingredients).getByRole('list', { name: 'Garnishes' });
  expect(ingredients.children).toHaveLength(3);
  expect(within(sauce).getAllByRole('listitem')).toHaveLength(1);
  expect(within(sauce).getByText('1 tbsp tamari')).toBeInTheDocument();
  expect(within(garnishes).getByText('1 tsp sesame seeds')).toBeInTheDocument();
  expect(screen.getByText(recipe.instructions[0])).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Show Less' }));
  expect(screen.queryByRole('list', { name: 'Ingredients' })).not.toBeInTheDocument();
});

test('shows source footnotes with their markers and links ingredient dependencies', () => {
  render(<RecipeCard recipe={{ ...recipe, source: 'database_exact', sourceNotes: '*Use spinach instead.\n**Use lemon juice.',
    relatedRecipes: [{ id: 'salad', title: 'Chickpea Salad with Tomatoes and Cucumber', sourceName: 'AHA',
      sourceUrl: 'https://recipes.heart.org/en/recipes/chickpea-salad-with-tomatoes-and-cucumber' }] }} />);
  fireEvent.click(screen.getByRole('button', { name: 'View Full Recipe' }));
  const notes = screen.getByRole('region', { name: 'Source notes' });
  expect(notes).toHaveTextContent('*Use spinach instead.');
  expect(notes).toHaveTextContent('**Use lemon juice.');
  const related = screen.getByRole('link', { name: 'Chickpea Salad with Tomatoes and Cucumber (AHA)' });
  expect(related).toHaveAttribute('href', 'https://recipes.heart.org/en/recipes/chickpea-salad-with-tomatoes-and-cucumber');
  expect(related).toHaveAttribute('rel', 'noopener noreferrer');
});

test('explains a missing footnote honestly and links to the source', () => {
  render(<RecipeCard recipe={{ ...recipe, ingredients: ["1 tbsp za'atar*"], source: 'database_exact', unresolvedFootnotes: ['*'],
    sourceUrl: 'https://www.aicr.org/cancer-prevention/recipes/sheet-pan-roasted-vegetables-and-beans/' }} />);
  fireEvent.click(screen.getByRole('button', { name: 'View Full Recipe' }));
  expect(screen.getByText("1 tbsp za'atar*")).toBeInTheDocument();
  expect(screen.getByText(/No matching footnote was included/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Check the original source' })).toHaveAttribute('target', '_blank');
});

test('does not present source notes for AI recipes or unsafe reference links', () => {
  const annotations = { sourceNotes: '*Source note.', unresolvedFootnotes: ['*'],
    relatedRecipes: [{ id: 'bad', title: 'Unsafe', sourceName: 'AHA', sourceUrl: 'javascript:alert(1)' }] };
  const { rerender } = render(<RecipeCard recipe={{ ...recipe, source: 'llm_generated', ...annotations }} />);
  fireEvent.click(screen.getByRole('button', { name: 'View Full Recipe' }));
  expect(screen.queryByRole('region', { name: 'Source notes' })).not.toBeInTheDocument();
  expect(screen.queryByRole('link', { name: /Unsafe/ })).not.toBeInTheDocument();
  rerender(<RecipeCard recipe={{ ...recipe, source: 'database_exact', ...annotations }} />);
  expect(screen.queryByRole('link', { name: /Unsafe/ })).not.toBeInTheDocument();
});
