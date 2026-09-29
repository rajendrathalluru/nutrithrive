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
