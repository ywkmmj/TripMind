import axios from 'axios'

import type {
  Itinerary,
  TripDetailResponse,
  TripEditPayload,
  TripListResponse,
  TripRequestPayload,
  TripSaveResponse,
  WeatherForecastResponse,
  PipelineResponse,
} from '../types'

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000,
});

// 深度清理对象，去除 Vue 响应式系统添加的内部属性
function deepCleanObject(obj: any): any {
    if (obj === null || obj === undefined) {
        return obj;
    }

    if (Array.isArray(obj)) {
        return obj.map(item => deepCleanObject(item));
    }

    if (typeof obj === 'object') {
        const cleaned: any = {};
        // 只使用 Object.keys，避免获取内部属性
        for (const key of Object.keys(obj)) {
            // 跳过以下划线开头的字段
            if (!key.startsWith('_')) {
                cleaned[key] = deepCleanObject(obj[key]);
            }
        }
        return cleaned;
    }

    return obj;
}

function camelToSnake(obj: any): any {
    if (Array.isArray(obj)) {
        return obj.map(v => camelToSnake(v));
    } else if (obj !== null && obj !== undefined && typeof obj === 'object') {
        return Object.keys(obj).reduce((acc: any, key) => {
            // 忽略下划线开头的私有字段（如 _type、__v 等）
            if (key.startsWith('_')) {
                return acc;
            }
            const snakeKey = key.replace(/([A-Z])/g, '_$1').toLowerCase();
            acc[snakeKey] = camelToSnake(obj[key]);
            return acc;
        }, {});
    }
    return obj;
}

// 创建干净的 payload，只包含需要的字段
function createCleanTripPayload(payload: any): any {
    // 首先深度清理对象，去除 Vue 响应式属性
    const cleaned = deepCleanObject(payload);
    return {
        destination: cleaned.destination,
        startDate: cleaned.startDate,
        endDate: cleaned.endDate,
        days: cleaned.days,
        travelers: cleaned.travelers,
        budget: cleaned.budget,
        preferences: cleaned.preferences || [],
        pace: cleaned.pace,
        dietaryPreferences: cleaned.dietaryPreferences || [],
        hotelLevel: cleaned.hotelLevel,
        specialNotes: cleaned.specialNotes,
    };
}

function snakeToCamel(obj: any): any {
  if (Array.isArray(obj)) {
    return obj.map(item => snakeToCamel(item));
  }
  
  if (obj && typeof obj === 'object') {
    const result: any = {};
    for (const key in obj) {
      if (Object.prototype.hasOwnProperty.call(obj, key)) {
        let newKey = key;
        if (key.includes('_')) {
          newKey = key.split('_').map((word, index) => {
            if (index === 0) {
              return word;
            }
            return word.charAt(0).toUpperCase() + word.slice(1);
          }).join('');
        }
        result[newKey] = snakeToCamel(obj[key]);
      }
    }
    return result;
  }
  
  return obj;
}

export async function generateTrip(payload: TripRequestPayload, mode: 'fast' | 'full' | 'async' = 'fast'): Promise<Itinerary> {
  const cleanPayload = createCleanTripPayload(payload);
  const snakePayload = camelToSnake(cleanPayload);
  const response = await api.post(`/trip/generate?mode=${mode}`, snakePayload);
  return snakeToCamel(response.data) as Itinerary;
}

export async function generateTripWithPipeline(
    payload: TripRequestPayload, 
    mode: 'fast' | 'full' | 'async' = 'fast'
): Promise<PipelineResponse> {
    const cleanPayload = createCleanTripPayload(payload);
    const snakePayload = camelToSnake(cleanPayload);
    const response = await api.post(`/trip/generate-multi-stage?mode=${mode}`, snakePayload);
    return snakeToCamel(response.data) as PipelineResponse;
}

// ========== ReAct Agent API ==========

export interface ReactAgentResponse {
  success: boolean;
  mode: "react_agent" | "fallback";
  fallbackUsed: boolean;
  itinerary: Itinerary | null;
  reactAnswer: string | null;
  steps: Array<{
    step: number;
    state?: string | null;
    thought?: string | null;
    action?: string;
    observation?: string;
    toolInput?: any;
  }>;
  toolCalls: number;
  error?: string | null;
}

export async function generateTripWithReact(payload: TripRequestPayload): Promise<ReactAgentResponse> {
  const snakePayload = camelToSnake(payload);
  const response = await api.post("/trip/generate-react", snakePayload);
  return snakeToCamel(response.data) as ReactAgentResponse;
}

export async function getReactTools(): Promise<Array<{ name: string; description: string }>> {
  const response = await api.get("/trip/react/tools");
  return response.data;
}

export async function editTrip(payload: TripEditPayload): Promise<Itinerary> {
  const snakePayload = camelToSnake(payload);
  const response = await api.post("/trip/edit", snakePayload);
  return snakeToCamel(response.data) as Itinerary;
}

export async function saveTrip(itinerary: Itinerary): Promise<TripSaveResponse> {
  const snakePayload = camelToSnake({
    tripId: itinerary.tripId,
    itinerary: itinerary,
    userId: "frontend_demo_user",
  });
  const response = await api.post("/trip/save", snakePayload);
  return snakeToCamel(response.data) as TripSaveResponse;
}

export async function listTrips(): Promise<TripListResponse> {
  const response = await api.get("/trip");
  return snakeToCamel(response.data) as TripListResponse;
}

export async function getTripDetail(tripId: string): Promise<TripDetailResponse> {
  const response = await api.get(`/trip/${tripId}`);
  return snakeToCamel(response.data) as TripDetailResponse;
}

export async function deleteTrip(tripId: string): Promise<void> {
  await api.delete(`/trip/${tripId}`);
}

export async function fetchWeatherForecast(city: string): Promise<WeatherForecastResponse> {
  const response = await api.get("/weather/forecast", {
    params: { city },
  });
  return snakeToCamel(response.data) as WeatherForecastResponse;
}

export function getMarkdownExportUrl(tripId: string): string {
  return `${API_BASE_URL}/export/${encodeURIComponent(tripId)}/markdown`;
}

export function getPdfExportUrl(tripId: string): string {
  return `${API_BASE_URL}/export/${encodeURIComponent(tripId)}/pdf`;
}

export default api;
