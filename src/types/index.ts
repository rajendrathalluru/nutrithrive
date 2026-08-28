export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  isLoading?: boolean;
  recipes?: Recipe[];
  backendData?: any;
}

export interface Recipe {
  id: string;
  title: string;
  description: string;
  type: string;
  calories: number;
  ingredients: string[];
  instructions: string[];
  tags: string[];
  aicrVerified: boolean;
  instructionsGenerated?: boolean;
  source?: string;
  verificationDetails?: any;
  helpfulTips?: string[];
  ingredientAdaptations?: string[];
  aicrCompliance?: any;
  dynamicallyAdapted?: boolean;
  cookTime?: string;
  servings?: number;
  difficulty?: string;
  nutrition?: {
    calories: number;
    protein?: number;
    carbs?: number;
    fat?: number;
  };
}

export interface Chat {
  id: string;
  title: string;
  messages: Message[];
  timestamp: Date;
}

export interface NutriThriveChatbotProps {
  onBackToHome?: () => void;
}

export interface ChatMessage {
  role: string;
  content: string;
}

export interface QueryRequest {
  query: string;
  mode: string;
  conversation_history?: ChatMessage[];
}

export interface BackendHealth {
  status: 'healthy' | 'starting' | 'failed' | 'offline';
  message: string;
  model_loaded: boolean;
  recipes_count: number;
  startup_in_progress?: boolean;
  initialization_error?: string | null;
}
