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
  entity_id?: number | null
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
  title: string,
  entityId?: number | null,
): Promise<Thread> {
  const data = await request<{ thread: Thread }>(
    `/api/v1/workspaces/${workspaceSlug}/threads`,
    {
      method: 'POST',
      body: JSON.stringify({
        title,
        entity_id: entityId ?? null,
      }),
    }
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
export type FlagSeverity = 'urgent' | 'review' | 'info'

export type FlagCategory =
  | 'stranger'
  | 'social_pressure'
  | 'money_scam'
  | 'body_sleep'
  | 'violence'
  | 'distress'
  | 'family'
  | 'personal_info'
  | 'sexual_curiosity'
  | 'adult_topics'
  | 'trust_isolation'
  | 'other'

export interface ContentFlag {
  id: number
  user_id: string
  thread_id: string
  message_content: string
  response_content: string
  reason: string
  severity: FlagSeverity
  category: FlagCategory
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

// ── Entities (Admin Prime roster) ──────────────────────────────

export type EntityAccentColor = 'cyan' | 'pink' | 'green' | 'yellow'

export type EntityRelationshipType =
  | 'direct_report'
  | 'peer'
  | 'skip_level'
  | 'stakeholder'
  | 'external'

export interface Entity {
  id: number
  name: string
  role: string | null
  accent_color: EntityAccentColor
  relationship_type: EntityRelationshipType
  status: 'active' | 'archived'
  created_at: string
  updated_at: string
  fact_count: number
  thread_count: number
  tags: string[]
}

export interface EntityTimelineEntry {
  id: number
  category: string
  fact: string
  status: string
  recorded_at: string
}

export async function getEntities(): Promise<Entity[]> {
  const data = await request<{ entities: Entity[] }>(`/api/v1/entities`)
  return data.entities ?? []
}

export async function createEntity(payload: {
  name: string
  title?: string
  relationship_type: EntityRelationshipType
  accent_color: EntityAccentColor
  first_note?: string
}): Promise<Entity> {
  const data = await request<{ entity: Entity }>(`/api/v1/entities`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return data.entity
}

export async function patchEntity(
  entityId: number,
  fields: Partial<{
    name: string
    role: string
    accent_color: EntityAccentColor
    relationship_type: EntityRelationshipType
    status: 'active' | 'archived'
    context: string
  }>,
): Promise<Entity> {
  const data = await request<{ entity: Entity }>(
    `/api/v1/entities/${entityId}`,
    { method: 'PATCH', body: JSON.stringify(fields) },
  )
  return data.entity
}

export async function addEntityTag(
  entityId: number,
  tag: string,
): Promise<string[]> {
  const data = await request<{ tags: string[] }>(
    `/api/v1/entities/${entityId}/tags`,
    { method: 'POST', body: JSON.stringify({ tag }) },
  )
  return data.tags ?? []
}

export async function removeEntityTag(
  entityId: number,
  tag: string,
): Promise<string[]> {
  const data = await request<{ tags: string[] }>(
    `/api/v1/entities/${entityId}/tags/${encodeURIComponent(tag)}`,
    { method: 'DELETE' },
  )
  return data.tags ?? []
}

export async function getEntityTimeline(
  entityId: number,
): Promise<EntityTimelineEntry[]> {
  const data = await request<{ timeline: EntityTimelineEntry[] }>(
    `/api/v1/entities/${entityId}/timeline`,
  )
  return data.timeline ?? []
}

export async function getEntityThreads(
  entityId: number,
): Promise<Thread[]> {
  const data = await request<{ threads: Thread[] }>(
    `/api/v1/entities/${entityId}/threads`,
  )
  return data.threads ?? []
}

// ── Med-Bay ───────────────────────────────────────────────────
export interface MedbayProtocolItem {
  id: number
  user_id: string
  supplement_name: string
  dose: string | null
  frequency: string | null
  reason: string | null
  target_marker: string | null
  started_at: string
  stopped_at: string | null
  status: 'active' | 'stopped'
}

export interface MedbayLabResult {
  id: number
  user_id: string
  marker_name: string
  value: number
  unit: string | null
  reference_low: number | null
  reference_high: number | null
  status: 'low' | 'normal' | 'high' | null
  test_date: string
  created_at: string
}

export interface MedbayLatestLab {
  marker_name: string
  id: number
  value: number
  unit: string | null
  reference_low: number | null
  reference_high: number | null
  status: 'low' | 'normal' | 'high' | null
  test_date: string
  previous_value: number | null
  previous_date: string | null
}

export interface MedbayFollowup {
  id: number
  user_id: string
  description: string
  reason: string | null
  suggested_date: string | null
  completed: boolean
  completed_at: string | null
  created_at: string
}

export type MedbayChangeType = 'added' | 'dose_change' | 'stopped'

export interface MedbayChange {
  id: number
  user_id: string
  change_type: MedbayChangeType | string
  item_name: string
  old_value: string | null
  new_value: string | null
  reason: string | null
  created_at: string
}

export async function getMedbayProtocol(
  includeStopped = false,
): Promise<MedbayProtocolItem[]> {
  const qs = includeStopped ? '?include_stopped=true' : ''
  const data = await request<{ protocol: MedbayProtocolItem[] }>(
    `/api/v1/medbay/protocol${qs}`,
  )
  return data.protocol ?? []
}

export async function getMedbayLabs(
  marker?: string,
): Promise<MedbayLabResult[]> {
  const qs = marker ? `?marker=${encodeURIComponent(marker)}` : ''
  const data = await request<{ labs: MedbayLabResult[] }>(
    `/api/v1/medbay/labs${qs}`,
  )
  return data.labs ?? []
}

export async function getMedbayLatestLabs(): Promise<MedbayLatestLab[]> {
  const data = await request<{ labs: MedbayLatestLab[] }>(
    `/api/v1/medbay/labs/latest`,
  )
  return data.labs ?? []
}

export async function getMedbayFollowups(
  includeCompleted = false,
): Promise<MedbayFollowup[]> {
  const qs = includeCompleted ? '?include_completed=true' : ''
  const data = await request<{ followups: MedbayFollowup[] }>(
    `/api/v1/medbay/followups${qs}`,
  )
  return data.followups ?? []
}

export async function getMedbayChanges(
  limit = 100,
): Promise<MedbayChange[]> {
  const data = await request<{ changes: MedbayChange[] }>(
    `/api/v1/medbay/changes?limit=${limit}`,
  )
  return data.changes ?? []
}

export async function completeMedbayFollowup(
  followupId: number,
): Promise<void> {
  await request<{ status: string }>(
    `/api/v1/medbay/followups/${followupId}/complete`,
    { method: 'PATCH' },
  )
}