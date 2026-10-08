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
