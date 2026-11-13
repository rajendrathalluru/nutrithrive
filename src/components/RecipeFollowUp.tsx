import React from 'react';

export interface FollowUp {
  question: string;
  choices: Array<{ label: string; instruction: string }>;
}

const RecipeFollowUp: React.FC<{ request: string; followUp: FollowUp; onDraft: (text: string) => void }> =
  ({ request, followUp, onDraft }) => {
    if (!followUp?.question?.trim() || !Array.isArray(followUp.choices) || followUp.choices.length < 2) return null;
    return (
      <section className="tw-follow-up" aria-label="Suggested follow-up">
        <p>{followUp.question}</p>
        <div>
          {followUp.choices.map((choice, index) => (
            <button key={index} type="button"
              onClick={() => onDraft(`${request}\nKeep my existing requirements. ${choice.instruction}`)}>
              {choice.label}
            </button>
          ))}
        </div>
      </section>
    );
  };

export default RecipeFollowUp;
