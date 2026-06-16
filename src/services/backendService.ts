import { Recipe } from '../types';
import { cleanBackendText, formatIngredients, formatInstructions } from '../utils/textCleaner';

export class BackendService {
  private static instance: BackendService;
  private readonly baseUrl: string;

  private constructor() {
    const configuredUrl = window.__APP_CONFIG__?.REACT_APP_BACKEND_URL?.trim()
      || process.env.REACT_APP_BACKEND_URL?.trim();

    if (configuredUrl) {
      this.baseUrl = configuredUrl.replace(/\/+$/, '');
      return;
    }

    if (typeof window !== 'undefined') {
      this.baseUrl = window.location.origin.replace(/\/+$/, '');
      return;
    }

    this.baseUrl = 'http://localhost:8000';
  }

  public static getInstance(): BackendService {
    if (!BackendService.instance) {
      BackendService.instance = new BackendService();
    }
    return BackendService.instance;
  }

  async checkHealth(): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUrl}/health`);
      if (!response.ok) {
        return false;
      }
      const health = await response.json();
      return health.status === 'healthy';
    } catch {
      return false;
    }
  }

  async searchRecipes(
    query: string,
    conversationHistory: Array<{role: string, content: string}> = []
  ): Promise<{ recipes: Recipe[], backendData: any }> {
    console.log('🔍 Sending query to backend with conversation history:', {
      query,
      historyLength: conversationHistory.length
    });

    let response: Response;

    try {
      response = await fetch(`${this.baseUrl}/ask`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: query,
          mode: 'auto',
          conversation_history: conversationHistory
        }),
      });
    } catch {
      throw new Error(
        `Unable to reach the backend at ${this.baseUrl}. Make sure the FastAPI server is running and reachable.`
      );
    }

    if (!response.ok) {
      const errorDetail = await this.extractErrorDetail(response);
      throw new Error(errorDetail || `Backend error: ${response.status} ${response.statusText}`);
    }

    const backendData = await response.json();
    console.log('📦 Full backend response:', backendData);

    const recipes = this.transformBackendResponse(backendData);

    return { recipes, backendData };
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  private transformBackendResponse(backendData: any): Recipe[] {
    console.log('🔄 Transforming backend data:', backendData);
    
    let recipeDocs: any[] = [];
    
    if (Array.isArray(backendData.source_documents)) {
      recipeDocs = backendData.source_documents;
    } else if (Array.isArray(backendData.results)) {
      recipeDocs = backendData.results;
    } else if (Array.isArray(backendData.recipes)) {
      recipeDocs = backendData.recipes;
    } else {
      console.log('❌ No recipe documents found in backend response');
      return [];
    }

    if (recipeDocs.length === 0) {
      console.log('❌ Empty recipe documents array');
      return [];
    }

    const recipes: Recipe[] = [];

    recipeDocs.forEach((doc: any, index: number) => {
      try {
        // Clean all text fields from backend
        const recipe: Recipe = {
          id: doc.id || `recipe-${index}-${Date.now()}`,
          title: cleanBackendText(doc.name || doc.title || 'Recipe'),
          description: cleanBackendText(doc.description || ''),
          type: cleanBackendText(doc.type || ''),
          calories: doc.calories ? parseFloat(doc.calories) : 0,
          ingredients: formatIngredients(Array.isArray(doc.ingredients) ? doc.ingredients : []),
          instructions: formatInstructions(Array.isArray(doc.instructions) ? doc.instructions : []),
          tags: this.generateTags(doc),
          aicrVerified: doc.aicr_compliance?.overall_compliant || false,
          instructionsGenerated: doc.instructions_generated || false,
          source: doc.source || 'database',
          verificationDetails: doc.verification_details,
          helpfulTips: doc.helpful_tips ? doc.helpful_tips.map((tip: string) => cleanBackendText(tip)) : [],
          ingredientAdaptations: doc.ingredient_adaptations ? doc.ingredient_adaptations.map((adapt: string) => cleanBackendText(adapt)) : [],
          aicrCompliance: doc.aicr_compliance,
          dynamicallyAdapted: doc.dynamically_adapted || false,
          cookTime: doc.cookTime || undefined,
          servings: doc.servings || undefined,
          difficulty: doc.difficulty || undefined,
          nutrition: {
            calories: doc.calories ? parseFloat(doc.calories) : 0,
            protein: doc.protein || undefined,
            carbs: doc.carbs || undefined,
            fat: doc.fat || undefined
          }
        };

        recipes.push(recipe);
        console.log(`✅ Processed recipe: ${recipe.title}`, recipe);
        
      } catch (error) {
        console.error(`❌ Error processing recipe ${index}:`, error);
      }
    });

    return recipes;
  }

  private generateTags(doc: any): string[] {
    const tags = [];
    
    if (doc.type) tags.push(cleanBackendText(doc.type));
    if (doc.aicr_compliance?.overall_compliant) tags.push('AICR Verified');
    if (doc.instructions_generated) tags.push('AI Enhanced');
    if (doc.dynamically_adapted) tags.push('Adapted');
    
    // Add equipment tags
    if (doc.equipment_required?.includes('microwave')) {
      tags.push('Microwave');
    }
    
    return Array.from(new Set(tags));
  }

  private async extractErrorDetail(response: Response): Promise<string> {
    try {
      const data = await response.json();

      if (typeof data?.detail === 'string') {
        return data.detail;
      }

      if (typeof data?.message === 'string') {
        return data.message;
      }
    } catch {
      // Ignore parse errors and fall back to status text.
    }

    return '';
  }
}
