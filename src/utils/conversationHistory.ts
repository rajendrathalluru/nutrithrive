import { ChatMessage, Message } from '../types';

export const buildConversationHistory = (messages: Message[]): ChatMessage[] =>
  messages.filter(message => !message.isLoading).map(message => {
    const history: ChatMessage = { role: message.role, content: message.content };
    if (message.role === 'assistant' && message.recipes?.length) {
      history.content += `\nPreviously shown recipes: ${message.recipes.map(recipe => recipe.title).join(' | ')}`;
      history.recipes = message.recipes.map(recipe => ({
        recipe_id: recipe.id,
        name: recipe.title,
        type: recipe.type,
        description: recipe.description,
        ingredients: recipe.ingredients,
        instructions: recipe.instructions,
        source: recipe.source,
        generated_by_llm: recipe.source === 'llm_generated',
        database_record_found: recipe.source === 'database_exact' || recipe.source === 'database_completed',
        source_name: recipe.sourceName,
        recipe_link: recipe.sourceUrl,
        source_notes: recipe.source === 'llm_generated' ? '' : recipe.sourceNotes,
        unresolved_footnotes: recipe.source === 'llm_generated' ? [] : recipe.unresolvedFootnotes,
        related_recipes: recipe.source === 'llm_generated' ? [] : recipe.relatedRecipes?.map(reference => ({
          recipe_id: reference.id, name: reference.title,
          recipe_link: reference.sourceUrl, source_name: reference.sourceName,
        })),
        total_time: recipe.totalTime,
        storage_instructions: recipe.storageGuidance,
        calories: recipe.calories,
        nutrition: recipe.nutrition,
      }));
    }
    return history;
  });
