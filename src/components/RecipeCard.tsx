import React, { useState } from 'react';
import { Zap, AlertCircle, FileText, Hash, Users, Clock, ExternalLink } from 'lucide-react';
import { Recipe } from '../types';

interface RecipeCardProps {
  recipe: Recipe;
}

const RecipeCard: React.FC<RecipeCardProps> = ({ recipe }) => {
  const [expanded, setExpanded] = useState(false);
  const helpfulTips = Array.isArray(recipe.helpfulTips) ? recipe.helpfulTips.filter(Boolean) : [];
  const ingredients = Array.isArray(recipe.ingredients) ? recipe.ingredients.filter(Boolean) : [];
  const instructions = Array.isArray(recipe.instructions) ? recipe.instructions.filter(Boolean) : [];
  const ingredientAdaptations = Array.isArray(recipe.ingredientAdaptations)
    ? recipe.ingredientAdaptations.filter(Boolean)
    : [];
  const isAiGenerated = recipe.source === 'llm_generated';
  const sourceLabel = recipe.sourceLabel || (isAiGenerated ? 'AI Generated' : 'Sourced from AICR');
  const sourceUrl = typeof recipe.sourceUrl === 'string' && /^https?:\/\//i.test(recipe.sourceUrl)
    ? recipe.sourceUrl
    : '';
  const sourceName = recipe.sourceName || 'AICR';
  const nutritionItems = [
    recipe.nutrition?.protein !== undefined && recipe.nutrition?.protein !== null
      ? { label: 'protein', value: `${recipe.nutrition.protein}g` }
      : null,
    recipe.nutrition?.carbs !== undefined && recipe.nutrition?.carbs !== null
      ? { label: 'carbs', value: `${recipe.nutrition.carbs}g` }
      : null,
    recipe.nutrition?.fat !== undefined && recipe.nutrition?.fat !== null
      ? { label: 'fat', value: `${recipe.nutrition.fat}g` }
      : null,
  ].filter(Boolean) as Array<{ label: string; value: string }>;

  return (
    <div className="overflow-hidden rounded-[26px] border border-slate-200 bg-white shadow-[0_18px_50px_rgba(15,23,42,0.08)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_22px_60px_rgba(15,23,42,0.12)]">
      <div className="p-5">
        {/* Header */}
        <div className="flex items-start justify-between mb-3">
          <h3 className="font-semibold text-slate-900 text-xl leading-tight">{recipe.title}</h3>
          <div className="flex flex-col items-end gap-1">
            {isAiGenerated ? (
              <span className="bg-violet-50 text-violet-700 text-xs px-2.5 py-1 rounded-full flex items-center gap-1 border border-violet-100">
                <Zap className="w-3 h-3" />
                {sourceLabel}
              </span>
            ) : null}
          </div>
        </div>
        
        {/* Description */}
        {recipe.description && (
          <p className="text-slate-600 text-sm mb-4 leading-6">{recipe.description}</p>
        )}
        
        {/* Metadata */}
        <div className="flex items-center gap-4 text-sm text-slate-500 mb-4">
          {recipe.cookTime && (
            <span className="flex items-center gap-1">
              <Clock className="w-4 h-4" />
              {recipe.cookTime}
            </span>
          )}
          {recipe.servings && (
            <span className="flex items-center gap-1">
              <Users className="w-4 h-4" />
              {recipe.servings} servings
            </span>
          )}
          {recipe.difficulty && (
            <span>{recipe.difficulty}</span>
          )}
        </div>
        
        {/* Calories */}
        {recipe.calories > 0 && (
          <div className="mb-3">
            <span className="bg-slate-100 text-slate-700 text-sm px-3 py-1 rounded-full border border-slate-200">
              {recipe.calories} calories
            </span>
          </div>
        )}
        
        {/* Tags */}
        {recipe.tags.length > 0 && (
          <div className="flex gap-2 flex-wrap mb-3">
            {recipe.tags.map((tag, idx) => (
              <span 
                key={idx} 
                className="bg-slate-50 text-slate-700 text-xs px-2.5 py-1 rounded-full border border-slate-200"
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        {!isAiGenerated && sourceUrl && (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mb-3 inline-flex items-center gap-1.5 text-sm font-medium text-sky-700 underline underline-offset-2 hover:text-sky-800"
          >
            Source: {sourceName}
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        )}

        {/* Expand/Collapse Button */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full bg-slate-900 text-white py-3 rounded-2xl hover:bg-slate-800 transition-colors font-medium"
        >
          {expanded ? 'Show Less' : 'View Full Recipe'}
        </button>
        
        {/* Expanded Content */}
        {expanded && (
          <div className="mt-5 pt-5 border-t border-slate-200 space-y-4">
            {/* Helpful Tips */}
            {helpfulTips.length > 0 && (
              <div className="bg-slate-50 rounded-2xl p-4 border border-slate-200">
                <h4 className="font-medium text-slate-900 mb-2 flex items-center gap-2">
                  <Zap className="w-4 h-4" />
                  Helpful Tips
                </h4>
                <ul className="text-sm text-slate-700 space-y-1">
                  {helpfulTips.map((tip, idx) => (
                    <li key={idx} className="flex items-start">
                      <span className="w-1.5 h-1.5 bg-slate-500 rounded-full mt-1.5 mr-2 flex-shrink-0"></span>
                      {tip}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            
            {/* Ingredients */}
            {ingredients.length > 0 && (
              <div>
                <h4 className="font-medium mb-2 flex items-center gap-2">
                  <FileText className="w-4 h-4" />
                  Ingredients
                </h4>
                <ul className="text-sm text-slate-700 space-y-1">
                  {ingredients.map((ingredient, idx) => (
                    <li key={idx} className="flex items-start">
                      <span className="w-2 h-2 bg-slate-500 rounded-full mt-1.5 mr-2 flex-shrink-0"></span>
                      {ingredient}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            
            {/* Instructions */}
            {instructions.length > 0 && (
              <div>
                <h4 className="font-medium mb-2 flex items-center gap-2">
                  <Hash className="w-4 h-4" />
                  Instructions
                </h4>
                <ol className="list-decimal pl-5 text-sm text-slate-700 space-y-2">
                  {instructions.map((instruction, idx) => (
                    <li key={idx} className="pl-1">{instruction}</li>
                  ))}
                </ol>
              </div>
            )}
            
            {/* Ingredient Adaptations */}
            {ingredientAdaptations.length > 0 && (
              <div className="bg-emerald-50 rounded-2xl p-4 border border-emerald-100">
                <h4 className="font-medium text-emerald-900 mb-2 flex items-center gap-2">
                  <AlertCircle className="w-4 h-4" />
                  Suggested Adaptations
                </h4>
                <ul className="text-sm text-emerald-800 space-y-1">
                  {ingredientAdaptations.map((adaptation, idx) => (
                    <li key={idx} className="flex items-start">
                      <span className="w-1.5 h-1.5 bg-green-500 rounded-full mt-1.5 mr-2 flex-shrink-0"></span>
                      {adaptation}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            
            {/* Nutrition Information */}
            {nutritionItems.length > 0 && (
              <div>
                <h4 className="font-medium mb-2">Nutrition (per serving)</h4>
                <div className="grid grid-cols-3 gap-2 text-sm">
                  {nutritionItems.map((item) => (
                    <div key={item.label} className="text-center p-2 bg-slate-50 rounded-2xl border border-slate-200">
                      <div className="font-semibold">{item.value}</div>
                      <div className="text-slate-500 text-xs">{item.label}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default RecipeCard;
