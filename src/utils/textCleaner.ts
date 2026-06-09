export const cleanBackendText = (text: string): string => {
  if (!text) return '';
  
  // Remove markdown-style symbols and emojis that don't render well
  return text
    .replace(/\*\*(.*?)\*\*/g, '$1') // Remove **bold** markers
    .replace(/\*(.*?)\*/g, '$1')     // Remove *italic* markers
    .replace(/_(.*?)_/g, '$1')       // Remove _underline_ markers
    .replace(/`(.*?)`/g, '$1')       // Remove `code` markers
    .replace(/[🌟✨🎯💫🌱📋🔥💪❤️🍃⭐🎉🔍📦📚🍳✅❌]/g, '') // Remove emojis
    .replace(/📝/g, '') // Remove specific emojis
    .replace(/🌱/g, '') // Nutrition optimized symbol
    .replace(/✨/g, '') // Custom generated symbol
    .replace(/\n\s*\n\s*\n/g, '\n\n') // Clean up excessive newlines
    .trim();
};

export const formatInstructions = (instructions: string[]): string[] => {
  return instructions
    .map((instruction) => cleanBackendText(instruction))
    .map((instruction) => instruction.replace(/^\s*(?:step\s*)?\d+[\).\:-]\s*/i, ''))
    .map((instruction) => instruction.replace(/^\s*[•*-]\s*/, ''))
    .filter(Boolean);
};

export const formatIngredients = (ingredients: string[]): string[] => {
  return ingredients.map(ingredient => cleanBackendText(ingredient));
};
