import axios, { AxiosError, AxiosRequestConfig, AxiosResponse } from "axios";
import { message } from "ant-design-vue";

// 定义错误类型
export enum ErrorCode {
  TIMEOUT = "TIMEOUT",
  NETWORK_ERROR = "NETWORK_ERROR",
  SERVER_ERROR = "SERVER_ERROR",
  UNKNOWN = "UNKNOWN",
}

export interface RequestError {
  code: ErrorCode;
  message: string;
  originalError?: any;
}

// 请求重试配置
export interface RetryConfig {
  maxRetries?: number;
  delay?: number;
  shouldRetry?: (error: AxiosError) => boolean;
}

// 默认重试配置
const defaultRetryConfig: RetryConfig = {
  maxRetries: 3,
  delay: 1000,
  shouldRetry: (error: AxiosError) => {
    if (!error.response) {
      return true;
    }
    const status = error.response.status;
    return [408, 429, 500, 502, 503, 504].includes(status);
  },
};

// 延迟函数
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// 创建 axios 实例
const apiClient = axios.create({
  timeout: 120000,
});

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// 响应拦截器
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    return response;
  },
  async (error: AxiosError) => {
    return Promise.reject(error);
  }
);

// 请求函数，带重试
export async function requestWithRetry<T>(
  config: AxiosRequestConfig,
  retryConfig?: RetryConfig
): Promise<T> {
  const maxRetries = retryConfig?.maxRetries ?? 3;
  const retryDelay = retryConfig?.delay ?? 1000;
  const shouldRetry = retryConfig?.shouldRetry ?? defaultRetryConfig.shouldRetry;

  let lastError: AxiosError | undefined;
  let attempts = 0;

  while (attempts <= maxRetries) {
    try {
      const response = await apiClient(config);
      return response.data as T;
    } catch (error) {
      lastError = error as AxiosError;
      attempts++;

      if (attempts <= maxRetries && shouldRetry && shouldRetry(lastError)) {
        await delay(retryDelay);
        continue;
      }
      break;
    }
  }

  const wrappedError: RequestError = {
    code: getErrorCode(lastError),
    message: getErrorMessage(lastError),
    originalError: lastError,
  };

  throw wrappedError;
}

function getErrorCode(error?: AxiosError): ErrorCode {
  if (!error) {
    return ErrorCode.UNKNOWN;
  }
  if (error.code === "ECONNABORTED" || error.message.includes("timeout")) {
    return ErrorCode.TIMEOUT;
  }
  if (!error.response) {
    return ErrorCode.NETWORK_ERROR;
  }
  if (error.response.status >= 500) {
    return ErrorCode.SERVER_ERROR;
  }
  return ErrorCode.UNKNOWN;
}

function getErrorMessage(error?: AxiosError): string {
  if (!error) {
    return "发生了未知错误";
  }
  if (error.code === "ECONNABORTED" || error.message.includes("timeout")) {
    return "请求超时，请稍后重试";
  }
  if (!error.response) {
    return "网络错误，请检查网络连接";
  }
  if (error.response.status >= 500) {
    return "服务器错误，请稍后重试";
  }
  return error.message || "发生了未知错误";
}

// 封装请求，带错误处理
export async function safeRequest<T>(
  config: AxiosRequestConfig,
  options?: {
    showError?: boolean;
    defaultErrorMessage?: string;
    retryConfig?: RetryConfig;
  }
): Promise<T | null> {
  const {
    showError = true,
    defaultErrorMessage = "请求失败",
    retryConfig,
  } = options || {};

  try {
    return await requestWithRetry<T>(config, retryConfig);
  } catch (error) {
    const errorMessage =
      (error as RequestError).message || defaultErrorMessage;
    if (showError) {
      message.error(errorMessage);
    }
    return null;
  }
}

export default apiClient;
