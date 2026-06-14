export interface TripRequestPayload {
  destination: string;
  startDate: string;
  endDate: string;
  days: number;
  travelers: number;
  budget: number;
  preferences: string[];
  pace?: string | null;
  dietaryPreferences: string[];
  hotelLevel?: string | null;
  specialNotes?: string | null;
}

export interface TripEditPayload {
  tripId: string;
  currentItinerary: Itinerary;
  userInstruction: string;
  editScope?: string | null;
  preserveConstraints: string[];
}

export interface PhotoItem {
  url: string;
  title?: string | null;
}

export interface SpotItem {
  name: string;
  startTime?: string | null;
  endTime?: string | null;
  description?: string | null;
  estimatedCost?: number;
  location?: string | null;
  imageUrl?: string | null;
  images: PhotoItem[];
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  poiId?: string | null;
  rating?: number | null;
  priceLevel?: string | null;
  openingHours?: string | null;
  phone?: string | null;
  website?: string | null;
  tags: string[];
  cityname?: string | null;
  adname?: string | null;
}

export interface MealItem {
  name: string;
  mealType: string;
  estimatedCost?: number;
  pricePerPerson?: number | null;
  notes?: string | null;
  imageUrl?: string | null;
  images: PhotoItem[];
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  poiId?: string | null;
  rating?: number | null;
  openingHours?: string | null;
  phone?: string | null;
  website?: string | null;
  cuisine: string[];
  tags: string[];
  cityname?: string | null;
  adname?: string | null;
}

export interface HotelItem {
  name: string;
  level?: string | null;
  starRating?: number | null;
  estimatedCost?: number;
  pricePerNight?: number | null;
  location?: string | null;
  imageUrl?: string | null;
  images: PhotoItem[];
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  poiId?: string | null;
  rating?: number | null;
  openingHours?: string | null;
  phone?: string | null;
  website?: string | null;
  facilities: string[];
  tags: string[];
  cityname?: string | null;
  adname?: string | null;
}

export interface TransportItem {
  mode: string;
  fromPlace?: string | null;
  toPlace?: string | null;
  estimatedCost?: number;
  duration?: string | null;
  distanceKm?: number | null;
  estimatedMinutes?: number | null;
}

export interface DayPlan {
  dayIndex: number;
  date?: string | null;
  theme?: string | null;
  spots: SpotItem[];
  meals: MealItem[];
  hotel?: HotelItem | null;
  transport: TransportItem[];
  notes: string[];
}

export interface BudgetBreakdown {
  transport: number;
  hotel: number;
  meals: number;
  tickets: number;
  insurance: number;
  contingency: number;
  shoppingMisc: number;
  total: number;
  totalForGroup: number;
  travelers: number;
  budgetAlert: string | null;
}

export interface Itinerary {
  tripId: string;
  destination: string;
  summary: string;
  days: DayPlan[];
  estimatedBudget: number;
  budgetBreakdown: BudgetBreakdown;
  tips: string[];
  sourceNotes: string[];
}

export interface TripSaveResponse {
  message: string;
  tripId: string;
}

export interface TripSummaryItem {
  tripId: string;
  destination: string;
  summary: string;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface TripListResponse {
  total: number;
  items: TripSummaryItem[];
}

export interface TripDetailResponse {
  tripId: string;
  itinerary: Itinerary;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface WeatherForecastDay {
  date?: string | null;
  week?: string | null;
  dayWeather?: string | null;
  nightWeather?: string | null;
  dayTemp?: string | null;
  nightTemp?: string | null;
  dayWind?: string | null;
  nightWind?: string | null;
}

export interface WeatherForecastResponse {
  city: string;
  province?: string | null;
  adcode?: string | null;
  reportTime?: string | null;
  days: WeatherForecastDay[];
}

export interface StageResult {
  stageType: string;
  status: string;
  startTime?: string | null;
  endTime?: string | null;
  durationMs?: number | null;
  output?: any;
  error?: string | null;
  warnings: string[];
  metadata: Record<string, any>;
}

export interface PipelineSummary {
  success: boolean;
  totalStages: number;
  completedStages: number;
  failedStages: number;
  totalWarnings: number;
  totalDurationMs?: number | null;
  stageResults: Record<string, StageResult>;
}

export interface PipelineResponse {
  success: boolean;
  itinerary?: Itinerary | null;
  summary: PipelineSummary;
  finalError?: string | null;
}
