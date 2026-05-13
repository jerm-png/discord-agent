const BASE_URL = ''

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

export interface Workspace {
  slug: string
  label: string
  memory_mode: string
  isolated: boolean
  entity_memory: boolean
}

export interface Thread {
  id: string
  workspace: string
  title: string
  created_at: string
  updated_at: string
  last_message_at: string | null
  status: string
  message_count: number
}

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const body = await res.json()
      msg = body.message || body.detail || msg
    } catch {}
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

export interface AuthUser {
  user_id: string
  role: 'admin' | 'user'
}

export async function login(
  password: string,
): Promise<{ message: string } & AuthUser> {
  const res = await fetch(`${BASE_URL}/api/v1/auth/login`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
  if (res.status !== 200) {
    let msg = 'Authentication failed'
    try {
      const body = await res.json()
      msg = body.message || body.detail || msg
    } catch {}
    throw new Error(msg)
  }
  return res.json()
}

export async function getMe(): Promise<AuthUser | null> {
  const res = await fetch(`${BASE_URL}/api/v1/auth/me`, {
    credentials: 'include',
  })
  if (res.status === 401) return null
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<AuthUser>
}

export async function logout(): Promise<void> {
  await fetch(`${BASE_URL}/api/v1/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  })
}

export async function getWorkspaces(): Promise<Workspace[]> {
  let res: Response
  try {
    res = await fetch(`${BASE_URL}/api/v1/workspaces`, {
      credentials: 'include',
    })
  } catch (e) {
    throw new Error('Network error')
  }
  if (res.status === 401) throw new Error('unauthorized')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  return data.workspaces as Workspace[]
}

export async function getThreads(workspaceSlug: string): Promise<Thread[]> {
  const data = await request<{ threads: Thread[] }>(
    `/api/v1/workspaces/${workspaceSlug}/threads`
  )
  return data.threads
}

export async function createThread(
  workspaceSlug: string,
  title: string
): Promise<Thread> {
  const data = await request<{ thread: Thread }>(
    `/api/v1/workspaces/${workspaceSlug}/threads`,
    { method: 'POST', body: JSON.stringify({ title }) }
  )
  return data.thread
}

export async function renameThread(
  threadId: string,
  title: string
): Promise<Thread> {
  const data = await request<{ thread: Thread }>(
    `/api/v1/workspaces/threads/${threadId}`,
    { method: 'PATCH', body: JSON.stringify({ title }) }
  )
  return data.thread
}

export async function archiveThread(threadId: string): Promise<void> {
  await request<unknown>(`/api/v1/workspaces/threads/${threadId}`, {
    method: 'DELETE',
  })
}

export async function getMessages(threadId: string): Promise<ChatMessage[]> {
  const data = await request<{ messages?: ChatMessage[] }>(
    `/api/v1/threads/${threadId}/messages`
  )
  // Fall back to [] if the response shape is unexpected — passing
  // undefined into setMessages would break the `messages.length === 0`
  // check downstream.
  return data.messages ?? []
}
export type ThreadAction =
  | 'approve'
  | 'cancel'
  | 'modify'
  | 'continue'
  | 'adjust'
  | 'skip'
  | 'retry'

export async function postThreadAction(
  threadId: string,
  action: ThreadAction,
  changes?: string
): Promise<{ status: string; action: string }> {
  return request<{ status: string; action: string }>(
    `/api/v1/threads/${threadId}/action`,
    {
      method: 'POST',
      body: JSON.stringify({ action, changes: changes || "" }),
    }
  )
}

export interface ContentFlag {
  id: number
  user_id: string
  thread_id: string
  message_content: string
  response_content: string
  reason: string
  flagged_at: string
  reviewed: boolean
  reviewed_at: string | null
}

export async function getUnreviewedFlags(): Promise<ContentFlag[]> {
  const data = await request<{ flags: ContentFlag[] }>(
    `/api/v1/flags/unreviewed`,
  )
  return data.flags ?? []
}

export async function reviewFlag(flagId: number): Promise<void> {
  await request<unknown>(`/api/v1/flags/${flagId}/review`, {
    method: 'POST',
  })
}