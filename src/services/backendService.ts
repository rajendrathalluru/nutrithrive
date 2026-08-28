import { BackendHealth, Recipe } from '../types';
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

  async getHealth(): Promise<BackendHealth> {
    try {
      const response = await fetch(`${this.baseUrl}/health`);
      if (!response.ok) {
        return {
          status: 'offline',
          message: 'Recipe service is unavailable.',
          model_loaded: false,
          recipes_count: 0
        };
      }
      const health = await response.json();
      return {
        status: health.status === 'healthy' || health.status === 'starting' || health.status === 'failed'
          ? health.status
          : 'offline',
        message: typeof health.message === 'string' ? health.message : 'Recipe service status unavailable.',
        model_loaded: Boolean(health.model_loaded),
        recipes_count: typeof health.recipes_count === 'number' ? health.recipes_count : 0,
        startup_in_progress: Boolean(health.startup_in_progress),
        initialization_error: typeof health.initialization_error === 'string' ? health.initialization_error : null
      };
    } catch {
      return {
        status: 'offline',
        message: 'Recipe service is offline.',
        model_loaded: false,
        recipes_count: 0
      };
    }
  }

  async checkHealth(): Promise<boolean> {
    const health = await this.getHealth();
    return health.status === 'healthy';
  }

  async searchRecipes(
    query: string,
    conversationHistory: Array<{role: string, content: string}> = []
  ): Promise<{ recipes: Recipe[], backendData: any }> {
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
    const recipes = this.transformBackendResponse(backendData);

    return { recipes, backendData };
  }

  async transcribeAudio(audioBlob: Blob): Promise<string> {
    const formData = new FormData();
    const extension = this.getAudioExtension(audioBlob.type);
    formData.append('file', audioBlob, `voice-input.${extension}`);

    let response: Response;

    try {
      response = await fetch(`${this.baseUrl}/transcribe`, {
        method: 'POST',
        body: formData,
      });
    } catch {
      throw new Error(
        `Unable to reach the backend at ${this.baseUrl}. Make sure the FastAPI server is running and reachable.`
      );
    }

    if (!response.ok) {
      const errorDetail = await this.extractErrorDetail(response);
      throw new Error(errorDetail || `Transcription failed: ${response.status} ${response.statusText}`);
    }

    const data = await response.json();
    return typeof data?.text === 'string' ? data.text.trim() : '';
  }

  async createRealtimeSession(offerSdp: string): Promise<string> {
    let response: Response;

    try {
      response = await fetch(`${this.baseUrl}/realtime/session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/sdp',
        },
        body: offerSdp,
      });
    } catch {
      throw new Error(
        `Unable to reach the backend at ${this.baseUrl}. Make sure the FastAPI server is running and reachable.`
      );
    }

    if (!response.ok) {
      const errorDetail = await this.extractErrorDetail(response);
      throw new Error(errorDetail || `Unable to initialize live voice session: ${response.status} ${response.statusText}`);
    }

    return response.text();
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  getWebSocketUrl(path: string): string {
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    const url = new URL(this.baseUrl);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    url.pathname = normalizedPath;
    url.search = '';
    url.hash = '';
    return url.toString();
  }

  private getAudioExtension(mimeType: string): string {
    if (mimeType.includes('webm')) return 'webm';
    if (mimeType.includes('mp4')) return 'mp4';
    if (mimeType.includes('mpeg')) return 'mp3';
    if (mimeType.includes('wav')) return 'wav';
    return 'webm';
  }

  private transformBackendResponse(backendData: any): Recipe[] {
    let recipeDocs: any[] = [];
    
    if (Array.isArray(backendData.source_documents)) {
      recipeDocs = backendData.source_documents;
    } else if (Array.isArray(backendData.results)) {
      recipeDocs = backendData.results;
    } else if (Array.isArray(backendData.recipes)) {
      recipeDocs = backendData.recipes;
    } else {
      return [];
    }

    if (recipeDocs.length === 0) {
      return [];
    }

    const recipes: Recipe[] = [];

    recipeDocs.forEach((doc: any, index: number) => {
      try {
        const recipe: Recipe = {
          id: doc.recipe_id || doc.id || `recipe-${index}`,
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
      } catch {
        return;
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
