import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import LandingPage from './LandingPage';

test('presents recipe inspiration with clear source and AI distinctions', () => {
  render(<LandingPage />);
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('A little inspiration.A little nourishment.');
  const sources = screen.getByRole('region', { name: 'Recipe database sources' });
  ['AICR', 'ACS', 'AHA'].forEach(source => {
    expect(within(sources).getByText(source)).toBeInTheDocument();
  });
  expect(screen.getByText('AI Generated')).toBeInTheDocument();
  expect(screen.getByText('Meal inspiration · AI-created image')).toBeInTheDocument();
  expect(screen.getByText('Source attribution does not imply endorsement of Thrivewell.')).toBeInTheDocument();
  expect(screen.queryByText(/AICR Verified|95%|satisfaction rate/i)).not.toBeInTheDocument();
  expect(screen.getByRole('img')).toHaveAccessibleName(/bowl of quinoa/i);
});

test.each(['Get Started', 'Find your next meal', 'Explore recipes', 'Let’s find something good'])(
  '%s retains the existing start-chat callback', name => {
    const onGetStarted = jest.fn();
    render(<LandingPage onGetStarted={onGetStarted} />);
    fireEvent.click(screen.getByRole('button', { name }));
    expect(onGetStarted).toHaveBeenCalledTimes(1);
  }
);

test('mobile navigation toggles and Escape returns focus to its control', () => {
  render(<LandingPage />);
  const menuButton = screen.getByRole('button', { name: 'Open menu' });
  expect(menuButton).toHaveAttribute('aria-expanded', 'false');
  expect(screen.queryByRole('navigation', { name: 'Mobile navigation' })).not.toBeInTheDocument();
  fireEvent.click(menuButton);
  expect(menuButton).toHaveAttribute('aria-expanded', 'true');
  const menu = screen.getByRole('navigation', { name: 'Mobile navigation' });
  expect(menu).toHaveAttribute('id', menuButton.getAttribute('aria-controls'));
  within(menu).getByRole('link', { name: 'How it works' }).focus();
  fireEvent.keyDown(window, { key: 'Escape' });
  expect(screen.queryByRole('navigation', { name: 'Mobile navigation' })).not.toBeInTheDocument();
  expect(menuButton).toHaveFocus();
  fireEvent.click(menuButton);
  fireEvent.click(screen.getByRole('button', { name: 'Close menu' }));
  expect(menuButton).toHaveAttribute('aria-expanded', 'false');
});

test('choosing a mobile navigation link or starting chat closes the menu', () => {
  const onGetStarted = jest.fn();
  render(<LandingPage onGetStarted={onGetStarted} />);
  fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
  const menu = screen.getByRole('navigation', { name: 'Mobile navigation' });
  fireEvent.click(within(menu).getByRole('link', { name: 'Recipe inspiration' }));
  expect(screen.queryByRole('navigation', { name: 'Mobile navigation' })).not.toBeInTheDocument();
  expect(onGetStarted).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
  fireEvent.click(screen.getByRole('button', { name: 'Get Started' }));
  expect(screen.queryByRole('navigation', { name: 'Mobile navigation' })).not.toBeInTheDocument();
  expect(onGetStarted).toHaveBeenCalledTimes(1);
});

test('all in-page links have real destinations, including the keyboard skip link', () => {
  render(<LandingPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
  screen.getAllByRole('link').forEach(link => {
    const destination = link.getAttribute('href') || '';
    expect(destination).not.toBe('');
    expect(destination).not.toBe('#');
    if (destination.startsWith('#')) {
      expect(document.getElementById(destination.slice(1))).toBeInTheDocument();
    }
  });
  expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#home-main');
  expect(screen.getByRole('main')).toHaveAttribute('tabindex', '-1');
});

test('FAQ disclosures explain session limits and medical-advice boundaries', () => {
  render(<LandingPage />);
  const followUpQuestion = screen.getByText('Can I ask follow-up questions?');
  const disclosure = followUpQuestion.closest('details');
  expect(disclosure).not.toHaveAttribute('open');
  fireEvent.click(followUpQuestion);
  expect(disclosure).toHaveAttribute('open');
  expect(screen.getByText(/Conversations are not currently saved across page refreshes/)).toBeVisible();
  fireEvent.click(followUpQuestion);
  expect(disclosure).not.toHaveAttribute('open');
  fireEvent.click(screen.getByText('Does Thrivewell replace advice from my care team?'));
  expect(screen.getByText(/not diagnosis or medical treatment/)).toBeVisible();
  expect(screen.getByText(/Please avoid sharing identifying health information/)).toBeInTheDocument();
});

test('the research link opens safely without replacing the app', () => {
  render(<LandingPage />);
  const researchLink = screen.getByRole('link', { name: 'Visit the UIC Vitality Lab' });
  expect(researchLink).toHaveAttribute('href', 'https://chicago.medicine.uic.edu/family-community-medicine/fcm-research/labs/vitality-lab/');
  expect(researchLink).toHaveAttribute('target', '_blank');
  expect(researchLink).toHaveAttribute('rel', 'noopener noreferrer');
});

test('unmounting the open mobile menu removes its keyboard listener', () => {
  const removeListener = jest.spyOn(window, 'removeEventListener');
  const { unmount } = render(<LandingPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
  unmount();
  expect(removeListener).toHaveBeenCalledWith('keydown', expect.any(Function));
  removeListener.mockRestore();
});
