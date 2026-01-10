// Type declarations for npm packages

declare module 'axios' {
  export interface AxiosRequestConfig {
    baseURL?: string
    headers?: Record<string, string>
    params?: any
    data?: any
    responseType?: 'json' | 'stream' | 'text' | 'blob' | 'arraybuffer' | 'document'
    signal?: AbortSignal
  }

  export interface AxiosResponse<T = any> {
    data: T
    status: number
    statusText: string
    headers: any
    config: AxiosRequestConfig
  }

  export interface AxiosError<T = any> extends Error {
    config: AxiosRequestConfig
    code?: string
    request?: any
    response?: AxiosResponse<T>
    isAxiosError: boolean
  }

  export interface AxiosInstance {
    request<T = any>(config: AxiosRequestConfig): Promise<AxiosResponse<T>>
    get<T = any>(url: string, config?: AxiosRequestConfig): Promise<AxiosResponse<T>>
    post<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<AxiosResponse<T>>
    put<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<AxiosResponse<T>>
    delete<T = any>(url: string, config?: AxiosRequestConfig): Promise<AxiosResponse<T>>
    interceptors: {
      request: {
        use(onFulfilled?: (config: AxiosRequestConfig) => AxiosRequestConfig | Promise<AxiosRequestConfig>, onRejected?: (error: any) => any): number
      }
      response: {
        use(onFulfilled?: (response: AxiosResponse) => AxiosResponse | Promise<AxiosResponse>, onRejected?: (error: any) => any): number
      }
    }
  }

  export interface AxiosStatic extends AxiosInstance {
    create(config?: AxiosRequestConfig): AxiosInstance
  }

  const axios: AxiosStatic
  export default axios
}

declare module 'clsx' {
  export type ClassValue = string | number | boolean | undefined | null | Record<string, boolean> | ClassValue[]
  export function clsx(...inputs: ClassValue[]): string
}

declare module 'tailwind-merge' {
  export function twMerge(...inputs: (string | undefined | null | false)[]): string
}

declare module 'class-variance-authority' {
  export type VariantProps<T> = {
    [K in keyof T]?: T[K] extends Record<string, any> ? keyof T[K] : never
  }

  export function cva(
    base: string,
    config?: {
      variants?: Record<string, Record<string, string>>
      defaultVariants?: Record<string, string>
    }
  ): (props?: Record<string, any>) => string
}
