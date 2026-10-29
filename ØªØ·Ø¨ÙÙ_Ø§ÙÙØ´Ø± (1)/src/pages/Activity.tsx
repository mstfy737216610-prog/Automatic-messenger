import { useState } from 'react'
import { Activity, RefreshCw } from 'lucide-react'
import { EmptyState, ErrorState, Loading, PageHeader } from '@/components/Common'
import { useAsync } from '@/hooks/useAsync'
import { api, formatDate } from '@/lib/api'
import type { Account, EventItem } from '@/types'

export default function ActivityPage() {
  const [account, setAccount] = useState('')
  const [level, setLevel] = useState('')
  const { data: accounts } = useAsync<Account[]>(() => api('/api/accounts'), [])
  const { data: events, loading, error, reload } = useAsync<EventItem[]>(() => api(`/api/events?limit=250${account ? `&account_id=${account}` : ''}`), [account], 15000)
  const filtered = events?.filter((event) => !level || event.level === level)
  return <div className="page-stack">
    <PageHeader title="سجل النشاط" description="سجل تشخيصي محلي للفحص والتعلم والمعالجة؛ لا يحتوي على المفتاح أو كلمات مرور البروكسي."
      actions={<button className="btn btn-secondary" onClick={() => void reload()}><RefreshCw size={17} />تحديث</button>} />
    <div className="list-toolbar"><select aria-label="حساب السجل" value={account} onChange={(e) => setAccount(e.target.value)}><option value="">كل الحسابات</option>{accounts?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><select aria-label="مستوى السجل" value={level} onChange={(e) => setLevel(e.target.value)}><option value="">كل المستويات</option><option value="info">معلومات</option><option value="warning">تنبيهات</option><option value="error">أخطاء</option></select></div>
    {loading && !events ? <Loading /> : error && !events ? <ErrorState message={error} retry={() => void reload()} /> : !filtered?.length ? <EmptyState title="لا توجد أحداث مطابقة" description="غيّر عوامل التصفية أو نفّذ فحصًا من صفحة الحسابات." /> : <div className="event-table-wrap"><table className="event-table"><thead><tr><th>الوقت</th><th>الحساب</th><th>الحدث</th><th>التفاصيل</th><th>المستوى</th></tr></thead><tbody>{filtered.map((event) => <tr key={event.id}><td>{formatDate(event.created_at)}</td><td>{event.account_name || 'النظام'}</td><td><code>{event.event}</code></td><td>{event.message}</td><td><span className={`event-level level-${event.level}`}>{event.level === 'error' ? 'خطأ' : event.level === 'warning' ? 'تنبيه' : 'معلومة'}</span></td></tr>)}</tbody></table></div>}
    <div className="retention-note"><Activity size={18} /><p>تُحذف السجلات والوسائط القديمة تلقائيًا وفق مدة الاحتفاظ، بينما تبقى بصمات منع التكرار الصغيرة حتى لا يُعاد نشر محتوى قديم.</p></div>
  </div>
}
