export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(path, { ...options, headers })
  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json') ? await response.json() : await response.text()
  if (!response.ok) {
    const detail = typeof payload === 'object' && payload?.detail ? payload.detail : `فشل الطلب (${response.status})`
    throw new ApiError(Array.isArray(detail) ? detail.map((item) => item.msg).join('، ') : String(detail), response.status)
  }
  return payload as T
}

export const jsonOptions = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
})

export const formatDate = (value?: string | null) => {
  if (!value) return 'لم يحدث بعد'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ar', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

export const platformNames: Record<string, string> = { x: 'إكس', tiktok: 'تيك توك', instagram: 'إنستغرام', telegram: 'تيليجرام' }
export const statusNames: Record<string, string> = {
  new: 'جديد', filtering: 'قيد الفلترة', pending_review: 'بانتظار المراجعة', ignored: 'متجاهل',
  approved: 'معتمد', queued: 'في الطابور', processing: 'قيد المعالجة', ready: 'جاهز — لم يُرسل',
  publishing: 'جارٍ النشر', published: 'منشور', publish_unknown: 'يحتاج تأكيدًا', rejected: 'مرفوض', failed: 'فشل',
}
export const sessionNames: Record<string, string> = {
  valid: 'جلسة نشطة', missing: 'لا توجد جلسة', expired: 'انتهت الجلسة', unknown: 'تحتاج فحصًا', error: 'خطأ في الجلسة',
}
