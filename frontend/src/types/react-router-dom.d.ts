declare module 'react-router-dom' {
  export const BrowserRouter: any
  export const Routes: any
  export const Route: any
  export const Link: any
  export const Outlet: any
  export function useNavigate(): any
  export function useParams(): any
  export function useLocation(): {
    pathname: string
    search: string
    hash: string
    state: any
    key: string
  }
}
