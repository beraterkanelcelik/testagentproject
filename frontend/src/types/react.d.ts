declare module 'react' {
  type Dispatch<T> = (value: T | ((prev: T) => T)) => void
  export function useState<T>(initial: T | (() => T)): [T, Dispatch<T>]
  export function useEffect(fn: () => void | (() => void), deps?: any[]): void
  export function useRef<T>(initial: T): { current: T }
  export function useCallback<T extends (...args: any[]) => any>(fn: T, deps?: any[]): T
  export function forwardRef<T, P = {}>(render: (props: P, ref: React.Ref<T>) => React.ReactElement | null): ((props: P & React.RefAttributes<T>) => React.ReactElement | null) & { displayName?: string }
  export const StrictMode: any
  export const Fragment: any
  export type MouseEvent<T = any> = any
  export type FormEvent<T = any> = any
  export type ChangeEvent<T = any> = any
  export type ReactNode = any
  export type ReactElement = any
  export type Ref<T> = any
  export type RefAttributes<T> = { ref?: Ref<T> }
  export interface ButtonHTMLAttributes<T> extends HTMLAttributes<T> {
    disabled?: boolean
    form?: string
    formAction?: string
    formEncType?: string
    formMethod?: string
    formNoValidate?: boolean
    formTarget?: string
    name?: string
    type?: 'button' | 'reset' | 'submit'
    value?: string | ReadonlyArray<string> | number
  }
  export interface HTMLAttributes<T> {
    className?: string
    id?: string
    [key: string]: any
  }
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
