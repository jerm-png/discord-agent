import { create } from 'zustand'
import type { Workspace, Thread } from '../api/client'

interface DriftStore {
  workspaces: Workspace[]
  activeWorkspace: string
  threads: Thread[]
  activeThread: Thread | null
  setWorkspaces: (w: Workspace[]) => void
  setActiveWorkspace: (slug: string) => void
  setThreads: (t: Thread[]) => void
  setActiveThread: (t: Thread | null) => void
  addThread: (t: Thread) => void
  updateThread: (t: Thread) => void
  removeThread: (id: string) => void
}

export const useDriftStore = create<DriftStore>((set) => ({
  workspaces: [],
  activeWorkspace: 'chief-of-staff',
  threads: [],
  activeThread: null,
  setWorkspaces: (workspaces) => set({ workspaces }),
  setActiveWorkspace: (activeWorkspace) =>
    set({ activeWorkspace, activeThread: null, threads: [] }),
  setThreads: (threads) => set({ threads }),
  setActiveThread: (activeThread) => set({ activeThread }),
  addThread: (thread) =>
    set((s) => ({ threads: [thread, ...s.threads] })),
  updateThread: (thread) =>
    set((s) => ({
      threads: s.threads.map((t) => (t.id === thread.id ? thread : t)),
    })),
  removeThread: (id) =>
    set((s) => ({ threads: s.threads.filter((t) => t.id !== id) })),
}))
