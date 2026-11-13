import { fireEvent, render, screen } from '@testing-library/react';
import RecipeFollowUp from './RecipeFollowUp';

test('shows the generated question and drafts the selected answer', () => {
  const onDraft = jest.fn();
  render(<RecipeFollowUp request="Chinese dinner for six under $20" onDraft={onDraft} followUp={{
    question: 'Would you like a make-ahead side?',
    choices: [
      { label: 'Make-ahead side', instruction: 'Suggest a side I can prepare ahead.' },
      { label: 'Quick side', instruction: 'Suggest a side I can prepare quickly.' },
    ],
  }} />);
  expect(screen.getByText('Would you like a make-ahead side?')).toBeInTheDocument();
  expect(screen.queryByText('Budget for the whole recipe')).not.toBeInTheDocument();
  expect(onDraft).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Make-ahead side' }));
  expect(onDraft).toHaveBeenCalledWith('Chinese dinner for six under $20\nKeep my existing requirements. Suggest a side I can prepare ahead.');
});
