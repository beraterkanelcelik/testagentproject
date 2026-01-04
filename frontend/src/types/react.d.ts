declare module 'react' {
  export function useState<T>(initial: T): [T, (value: T) => void]
  export function useEffect(fn: () => void | (() => void), deps?: any[]): void
  export function useRef<T>(initial: T): { current: T }
  export const StrictMode: any
  export const Fragment: any
  export type MouseEvent<T = any> = any
  export type FormEvent<T = any> = any
  export type ChangeEvent<T = any> = any
  export type ReactNode = any
  export type ReactElement = any
  const React: any
  export default React
}

declare module 'react/jsx-runtime' {
  export const jsx: any
  export const jsxs: any
  export const Fragment: any
}

declare global {
  namespace JSX {
    interface IntrinsicElements {
      [elemName: string]: any
    }
    interface Element extends any {}
  }
}

export {}
