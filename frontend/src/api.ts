export type Role = 'student' | 'teacher' | 'dean' | 'admin'
export type Session = { status: 'authenticated'; access_token: string; id: number; role: Role }
export type AuthResult = Session | {status:'consent_required';version:string}
export type Room = { id: number; building: string; code: string; capacity: number | null; kind: string | null; floor: number | null; plan_x?:number|null; plan_y?:number|null; accessible: boolean | null; equipment: Record<string, number> }
export type Interval = { start: string; end: string }
export type Option = Interval & { room_id: number; building?: string; room?: string; explanation?: string; coverage?: string }
export type Booking = Interval & { id: number; room_id: number; owner_id: number; title: string; cancelled_at: string | null }
export type Teacher = { building: string; number: number; label: string }
export type Lesson = Interval & { id: number; subject: string; groups: string[]; teachers: Teacher[]; building: string | null; room: string | null }
export type Batch = { id: number; scope: string; state: string; complete: boolean; report: { input_rows: number; lessons: number; errors: number; unknown_room_lessons: number; overlapping_room_rows: number; booking_conflicts: (Interval & {room_id:number})[]; issues: {row:number;message:string}[] }; preview?: Lesson[] }
export class ApiError extends Error {
  constructor(public status: number, message: string, public alternatives: Option[] = [], public code?:string) { super(message) }
}

let session: Session | undefined
let refreshing: Promise<AuthResult> | undefined
let generation = 0
export function setSession(value?: Session) { generation++; session = value }

export async function api<T>(path: string, init?: RequestInit, retry = true): Promise<T> {
  const headers = new Headers(init?.headers)
  if (session) headers.set('Authorization', 'Bearer ' + session.access_token)
  const timeout = AbortSignal.timeout(path === '/auth/refresh' || path === '/privacy/policy' ? 8000 : 180000)
  let response: Response
  try {
    response = await fetch('/api/v1' + path, {
      ...init, headers, signal: init?.signal ? AbortSignal.any([init.signal, timeout]) : timeout,
    })
  } catch {
    throw new ApiError(503, 'Сервер CampusFlow недоступен. Проверьте запуск API и повторите попытку.')
  }
  const mime=response.headers.get('content-type')?.split(';')[0]
  if(response.ok&&(mime==='application/pdf'||mime==='application/vnd.openxmlformats-officedocument.wordprocessingml.document')){
    return await response.blob() as T
  }
  const body=response.status===204?undefined:await response.json().catch(()=>undefined)
  if (response.status === 401 && retry && session && !['/auth/login','/auth/refresh','/auth/consent','/auth/logout'].includes(path)) {
    const current = generation
    refreshing ??= api<AuthResult>('/auth/refresh', { method: 'POST' }, false).finally(() => { refreshing = undefined })
    const refreshed = await refreshing
    if (generation !== current) throw new ApiError(401, 'Сеанс изменился')
    if(refreshed.status==='consent_required'){
      setSession()
      window.dispatchEvent(new CustomEvent('cf-consent-required',{detail:refreshed.version}))
      throw new ApiError(401,'Подтвердите новую редакцию документов.')
    }
    session = refreshed
    return api<T>(path, init, false)
  }
  if (!response.ok) {
    if(body?.code==='no_coverage')throw new ApiError(response.status,'Расписание этого корпуса на выбранный день ещё не подтверждено. Выберите другую дату или корпус.',[],body.code)
    if (response.status >= 500 && !body?.detail) throw new ApiError(response.status, 'Сервер CampusFlow недоступен. Повторите попытку.')
    const detail = body?.detail
    throw new ApiError(response.status, typeof detail === 'string' ? detail : detail?.message ||
      (detail?.conflicts?.length ? 'Есть конфликтующих интервалов: ' + detail.conflicts.length : 'Не удалось выполнить запрос.'), detail?.alternatives, body?.code)
  }
  return body as T
}

export function json(data: unknown, method = 'POST', key?: string): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json', ...(key ? { 'Idempotency-Key': key } : {}) }, body: JSON.stringify(data) }
}

export async function occupancyEvents(signal: AbortSignal, onChange: () => void) {
  const response = await fetch('/api/v1/events', {
    signal, headers: session ? { Authorization: 'Bearer ' + session.access_token } : {},
  })
  if (!response.ok || !response.body) return
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += value
      let end = buffer.indexOf('\n\n')
      while (end >= 0) {
        if (buffer.slice(0, end).startsWith('event: occupancy')) onChange()
        buffer = buffer.slice(end + 2)
        end = buffer.indexOf('\n\n')
      }
    }
  } finally { reader.releaseLock() }
}
