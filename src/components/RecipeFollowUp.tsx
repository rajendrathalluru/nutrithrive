import React from 'react';
import { Sparkles, ArrowUpRight } from 'lucide-react';

export interface FollowUp {
  question: string;
  choices: Array<{ label: string; instruction: string }>;
}

const RecipeFollowUp: React.FC<{ followUp: FollowUp; onDraft: (text: string) => void }> =
  ({ followUp, onDraft }) => {
    if (!followUp?.question?.trim() || !Array.isArray(followUp.choices) || followUp.choices.length < 2) return null;
    return (
      <section className="tw-follow-up" aria-label="Suggested follow-up">
        <p className="tw-follow-up-question">
          <Sparkles size={14} aria-hidden="true" className="text-[#56774e] shrink-0" />
          <span>{followUp.question}</span>
        </p>
        <div className="tw-follow-up-choices">
          {followUp.choices.map((choice, index) => (
            <button
              key={index}
              type="button"
              className="tw-follow-up-chip"
              onClick={() => onDraft(choice.instruction.trim())}
            >
              <span>{choice.label}</span>
              <ArrowUpRight size={14} aria-hidden="true" className="tw-follow-up-chip-icon" />
            </button>
          ))}
        </div>
      </section>
    );
  };

export default RecipeFollowUp;
