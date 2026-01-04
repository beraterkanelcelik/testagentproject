/**
 * Authentication store using Zustand.
 */
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { StateCreator } from 'zustand'
import { authAPI } from '@/lib/api'
import { setAuthTokens, clearAuthTokens } from '@/lib/auth'

interface User {
  id: number
  email: string
  // Add other user fields as needed
}

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  signup: (email: string, password: string, first_name?: string, last_name?: string) => Promise<void>
  logout: () => Promise<void>
  setUser: (user: User | null) => void
}

export const useAuthStore = create<AuthState>(
  persist(
    ((set: (partial: AuthState | Partial<AuthState> | ((state: AuthState) => AuthState | Partial<AuthState>)) => void) => ({
      user: null,
      isAuthenticated: false,

      login: async (email: string, password: string) => {
        try {
          const response = await authAPI.login({ email, password })
          const { access, refresh, user } = response.data
          setAuthTokens({ access, refresh })
          set({ user, isAuthenticated: true })
        } catch (error) {
          throw error
        }
      },

      signup: async (email: string, password: string, first_name?: string, last_name?: string) => {
        try {
          const response = await authAPI.signup({ email, password, first_name, last_name })
          const { access, refresh, user } = response.data
          setAuthTokens({ access, refresh })
          set({ user, isAuthenticated: true })
        } catch (error) {
          throw error
        }
      },

      logout: async () => {
        try {
          await authAPI.logout()
        } catch (error) {
          // Continue with logout even if API call fails
        } finally {
          clearAuthTokens()
          set({ user: null, isAuthenticated: false })
        }
      },

      setUser: (user: User | null) => {
        set({ user, isAuthenticated: !!user })
      },
    })),
    {
      name: 'auth-storage',
      storage: createJSONStorage(() => localStorage),
    }
  )
)
