import { create } from 'zustand'

export type UserRole = 'admin' | 'user'

interface AuthStore {
  isAuthenticated: boolean
  userId: string | null
  role: UserRole | null
  setAuthenticated: (value: boolean) => void
  setUser: (userId: string, role: UserRole) => void
  clearUser: () => void
}

export const useAuthStore = create<AuthStore>((set) => ({
  isAuthenticated: false,
  userId: null,
  role: null,
  setAuthenticated: (value) => set({ isAuthenticated: value }),
  setUser: (userId, role) => set({
    isAuthenticated: true,
    userId,
    role,
  }),
  clearUser: () => set({
    isAuthenticated: false,
    userId: null,
    role: null,
  }),
}))
