declare module 'react-router-dom' {
  export const BrowserRouter: any
  export const Routes: any
  export const Route: any
  export const Link: any
  export const Outlet: any
  export function useNavigate(): (to: string | number, options?: { state?: any; replace?: boolean }) => void
  export function useParams(): Record<string, string | undefined>
  export function useLocation(): {
    pathname: string
    search: string
    hash: string
    state: any
    key: string
  }
}
