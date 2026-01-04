// Ambient type declarations for React and related modules

declare namespace React {
  interface Component<P = {}, S = {}, SS = any> {}
  type ReactNode = any
  type ReactElement = any
  type ComponentType<P = {}> = (props: P) => ReactElement | null
  
  interface MouseEvent<T = Element> extends SyntheticEvent<T> {}
  interface FormEvent<T = Element> extends SyntheticEvent<T> {}
  interface ChangeEvent<T = Element> extends SyntheticEvent<T> {}
  interface SyntheticEvent<T = Element> extends Event {
    currentTarget: EventTarget & T
    target: EventTarget & T
    preventDefault(): void
    stopPropagation(): void
  }
}

declare namespace JSX {
  interface IntrinsicElements {
    [elemName: string]: any
  }
  interface Element extends React.ReactElement {}
}

declare module 'react' {
  export const useState: <T>(initial: T) => [T, (value: T) => void]
  export const useEffect: (fn: () => void | (() => void), deps?: any[]) => void
  export const useRef: <T>(initial: T) => { current: T }
  export const StrictMode: React.ComponentType<{ children?: React.ReactNode }>
  export const Fragment: React.ComponentType<{ children?: React.ReactNode }>
  export type MouseEvent<T = Element> = React.MouseEvent<T>
  export type FormEvent<T = Element> = React.FormEvent<T>
  export type ChangeEvent<T = Element> = React.ChangeEvent<T>
  export type ReactNode = React.ReactNode
  export type ReactElement = React.ReactElement
  const React: {
    useState: <T>(initial: T) => [T, (value: T) => void]
    useEffect: (fn: () => void | (() => void), deps?: any[]) => void
    useRef: <T>(initial: T) => { current: T }
    StrictMode: React.ComponentType<{ children?: React.ReactNode }>
    Fragment: React.ComponentType<{ children?: React.ReactNode }>
  }
  export default React
}

declare module 'react-dom' {
  export const render: any
}

declare module 'react-dom/client' {
  export function createRoot(container: any): {
    render(children: any): void
    unmount(): void
  }
}

declare module 'react-router-dom' {
  import * as React from 'react'
  export const BrowserRouter: React.ComponentType<{ children?: React.ReactNode }>
  export const Routes: React.ComponentType<{ children?: React.ReactNode }>
  export const Route: React.ComponentType<{
    path?: string
    element?: React.ReactElement
    index?: boolean
    children?: React.ReactNode
  }>
  export const Link: React.ComponentType<{
    to: string
    children?: React.ReactNode
    className?: string
  }>
  export const Outlet: React.ComponentType
  export function useNavigate(): (to: string) => void
  export function useParams(): Record<string, string | undefined>
}

declare module 'react/jsx-runtime' {
  import * as React from 'react'
  export const jsx: (type: any, props: any, key?: any) => React.ReactElement
  export const jsxs: (type: any, props: any, key?: any) => React.ReactElement
  export const Fragment: React.ComponentType<{ children?: React.ReactNode }>
}

declare module 'sonner' {
  import * as React from 'react'
  export const toast: {
    (message: string, options?: any): void
    success: (message: string, options?: any) => void
    error: (message: string, options?: any) => void
    info: (message: string, options?: any) => void
    warning: (message: string, options?: any) => void
  }
  export function Toaster(props: { position?: string }): React.ReactElement
}

declare module 'zustand' {
  export function create<T = any>(fn?: any): () => T
  export type StateCreator<T = any, M = any, E = any> = any
}

declare module 'zustand/middleware' {
  export function persist(fn: any, options: any): any
  export function createJSONStorage(fn: any): any
}
