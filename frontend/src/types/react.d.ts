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
  export interface KeyboardEvent<T = any> {
    key: string
    shiftKey: boolean
    preventDefault: () => void
    stopPropagation: () => void
    [key: string]: any
  }
  export type ReactNode = any
  export type ReactElement = any
  export type Ref<T> = any
  export type RefAttributes<T> = { ref?: Ref<T> }
  // Special React props that should be excluded from component prop types
  export interface Attributes {
    key?: string | number | null
  }
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
    // React's special props that should be excluded from component prop types
    interface ElementAttributesProperty {
      props: {}
    }
    interface ElementChildrenAttribute {
      children: {}
    }
    // Allow key prop on all elements
    interface ElementClass {
      render(): any
    }
  }
  
  // Make key a valid prop on all React components
  namespace React {
    interface Attributes {
      key?: React.Key | null
    }
    type Key = string | number
  }
}

export {}
