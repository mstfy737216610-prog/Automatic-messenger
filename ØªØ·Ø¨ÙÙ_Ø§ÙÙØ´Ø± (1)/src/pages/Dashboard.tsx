import { useState } from 'react'
import { ArrowLeft, CheckCircle2, CircleAlert, Clock3, Radar, Send } from 'lucide-react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { EmptyState, ErrorState, Loading, PageHeader, StatusBadge } from '@/components/Common'
import { useAsync } from '@/hooks/useAsync'
import { api, formatDate, jsonOptions, platformNames, sessionNames } from '@/lib/api'
import type { DashboardData } from '@/types'

export default function Dashboard() {
  const { data, loading, error, reload } = useAsync<DashboardData>(() => api('/api/dashboard'), [], 20000)
  const [scanning, setScanning] = useState(false)
  const scanAll = async () => {
    if (!data?.accounts.length) return toast.info('أضف حسابًا ومصدرًا أولًا')
    const enabled = data.accounts.filter((account) => account.enabled)
    if (!enabled.length) return toast.info('فعّل حسابًا واحدًا على الأقل من صفحة الحسابات')
    setScanning(true)
    try {
      await Promise.all(enabled.map((account) => api(`/api/accounts/${account.id}/monitor`, jsonOptions('POST'))))
      toast.success(`أُضيف فحص ${enabled.length} حسابات إلى الطابور`)
      await reload(true)
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : 'تعذّر بدء الفحص') }
    finally { setScanning(false) }
  }
  if (loading && !data) return <Loading />
  if (error && !data) return <ErrorState message={error} retry={() => void reload()} />
  if (!data) return null
  const { stats } = data
  const cards = [
    { label: 'بانتظار المراجعة', value: stats.pending, icon: Clock3, tone: 'mint', to: '/review' },
    { label: 'جاهز في وضع الاختبار', value: stats.ready, icon: CheckCircle2, tone: 'plain', to: '/review' },
    { label: 'تم نشره وتأكيده', value: stats.published, icon: Send, tone: 'plain', to: '/review' },
    { label: 'يحتاج تدخلك', value: stats.failed, icon: CircleAlert, tone: stats.failed ? 'danger' : 'plain', to: '/activity' },
  ]
  return <div className="page-stack">
    <PageHeader title="صباح الخير، غرفة العمليات جاهزة" description="راقب القرارات قبل المحتوى؛ لا يُنشر شيء تلقائيًا ما لم تستوفِ شروطك."
      actions={<button className="btn btn-primary" onClick={() => void scanAll()} disabled={scanning}><Radar size={18} />{scanning ? 'جارٍ الإضافة…' : 'فحص الحسابات النشطة'}</button>} />
    <section className="metrics-grid" aria-label="ملخص العمل">
      {cards.map(({ label, value, icon: Icon, tone, to }) => <Link to={to} className={`metric metric-${tone}`} key={label}>
        <div><span>{label}</span><strong>{value}</strong></div><Icon size={22} />
      </Link>)}
    </section>
    <section className="operations-strip">
      <div><span className="section-label">سير العمل الآن</span><strong>{stats.active_jobs} مهام نشطة</strong></div>
      <div className="pipeline" aria-label="مراحل المعالجة">
        <span>مراقبة</span><ArrowLeft size={16} /><span>فلترة</span><ArrowLeft size={16} /><span className={stats.pending ? 'current' : ''}>مراجعة</span><ArrowLeft size={16} /><span>تجهيز ونشر</span>
      </div>
      <Link to="/accounts" className="text-link">{stats.enabled_accounts} من {stats.accounts} حسابات مفعّلة <ArrowLeft size={15} /></Link>
    </section>
    <div className="dashboard-grid">
      <section className="panel">
        <div className="panel-heading"><div><span className="section-label">حالة الحسابات</span><h2>الجلسات والمصادر</h2></div><Link to="/accounts" className="text-link">إدارة الكل <ArrowLeft size={15} /></Link></div>
        {data.accounts.length ? <div className="account-health-list">{data.accounts.map((account) => <div className="health-row" key={account.id}>
          <div className={`platform-letter platform-${account.platform}`}>{platformNames[account.platform]?.slice(0, 1)}</div>
          <div className="health-main"><strong>{account.name}</strong><span>{platformNames[account.platform]} · {account.sources?.length ?? '—'} مصادر</span></div>
          <span className={`session session-${account.session_status}`}>{sessionNames[account.session_status] || account.session_status}</span>
          <span className={account.enabled ? 'enabled-label' : 'muted-label'}>{account.enabled ? 'مفعّل' : 'متوقف'}</span>
        </div>)}</div> : <EmptyState title="ابدأ بحساب واحد" description="أضف حساب الوجهة، ثم مصدرًا واحدًا واختبر المسار قبل التوسع." action={<Link className="btn btn-secondary" to="/accounts">إضافة حساب</Link>} />}
      </section>
      <section className="panel">
        <div className="panel-heading"><div><span className="section-label">آخر القرارات</span><h2>حديث السجل</h2></div><Link to="/activity" className="text-link">السجل الكامل <ArrowLeft size={15} /></Link></div>
        {data.events.length ? <div className="timeline">{data.events.slice(0, 6).map((event) => <div className="timeline-item" key={event.id}>
          <span className={`timeline-dot level-${event.level}`} /><div><strong>{event.message}</strong><span>{event.account_name || 'النظام'} · {formatDate(event.created_at)}</span></div>
        </div>)}</div> : <EmptyState title="لا يوجد نشاط بعد" description="ستظهر هنا الفحوصات وقرارات الذكاء الاصطناعي ومراجعاتك." />}
      </section>
    </div>
    <section className="panel">
      <div className="panel-heading"><div><span className="section-label">أحدث المحتوى</span><h2>من الاكتشاف إلى القرار</h2></div><Link to="/review" className="text-link">فتح المراجعة <ArrowLeft size={15} /></Link></div>
      {data.recent_posts.length ? <div className="compact-posts">{data.recent_posts.map((post) => <Link to={`/review?post=${post.id}`} className="compact-post" key={post.id}>
        <div><strong>{post.account_name}</strong><span>من {post.source_handle || post.author || 'مصدر'} · {formatDate(post.created_at)}</span></div>
        <p>{post.processed_text || post.raw_text || 'منشور وسائط دون نص'}</p><StatusBadge status={post.status} />
      </Link>)}</div> : <EmptyState title="لا توجد منشورات في السجل" description="بعد أول فحص ستجد النص وقرار الفلترة والمعاينة هنا." />}
    </section>
  </div>
}
