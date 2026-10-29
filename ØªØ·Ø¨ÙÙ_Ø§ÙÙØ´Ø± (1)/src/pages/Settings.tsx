import { useState } from 'react'
import { Archive, CheckCircle2, Database, Download, FileKey2, Globe2, HardDrive, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { EmptyState, ErrorState, Loading, PageHeader } from '@/components/Common'
import { useAsync } from '@/hooks/useAsync'
import { api, jsonOptions } from '@/lib/api'
import type { Health } from '@/types'

type ProxyData = { count: number; proxies: { masked: string; assigned_to?: string }[] }
export default function SettingsPage() {
  const { data: health, loading, error, reload } = useAsync<Health>(() => api('/api/health'), [], 20000)
  const { data: proxies, reload: reloadProxies } = useAsync<ProxyData>(() => api('/api/proxies'), [])
  const [backup, setBackup] = useState('')
  const [busy, setBusy] = useState('')
  const createBackup = async () => {
    setBusy('backup')
    try { const result = await api<{ file: string; download_url: string }>('/api/maintenance/backup', jsonOptions('POST')); setBackup(result.download_url); toast.success(`أُنشئت النسخة: ${result.file}`) }
    catch (reason) { toast.error(reason instanceof Error ? reason.message : 'فشل النسخ الاحتياطي') }
    finally { setBusy('') }
  }
  const cleanup = async () => {
    setBusy('cleanup')
    try { await api('/api/maintenance/cleanup', jsonOptions('POST')); toast.success('اكتمل تنظيف السجلات والوسائط القديمة'); await reload() }
    catch (reason) { toast.error(reason instanceof Error ? reason.message : 'فشل التنظيف') }
    finally { setBusy('') }
  }
  if (loading && !health) return <Loading />
  if (error && !health) return <ErrorState message={error} retry={() => void reload()} />
  return <div className="page-stack">
    <PageHeader title="إعدادات النظام والتخزين" description="فحص صحة البيئة، النسخ المضغوطة، وتعيين عزل الشبكة دون كشف بيانات الاعتماد."
      actions={<button className="btn btn-secondary" onClick={() => { void reload(); void reloadProxies() }}><RefreshCw size={17} />فحص الحالة</button>} />
    <section className="system-grid">
      <div className="system-item"><Database size={20} /><div><span>قاعدة البيانات</span><strong>SQLite · {health?.database}</strong></div><CheckCircle2 className="ok-icon" size={19} /></div>
      <div className="system-item"><Globe2 size={20} /><div><span>Chromium</span><strong>{health?.chromium_configured ? 'المسار مضبوط' : 'يحتاج إعداد المسار'}</strong></div><span className={health?.chromium_configured ? 'health-dot ok' : 'health-dot warn'} /></div>
      <div className="system-item"><HardDrive size={20} /><div><span>معالجة الوسائط</span><strong>FFmpeg {health?.ffmpeg_configured ? 'جاهز' : 'غير جاهز'} · OCR {health?.tesseract_configured ? 'جاهز' : 'غير جاهز'}</strong></div><span className={health?.ffmpeg_configured && health?.tesseract_configured ? 'health-dot ok' : 'health-dot warn'} /></div>
      <div className="system-item"><ShieldCheck size={20} /><div><span>حاجز النشر</span><strong>{health?.dry_run || !health?.publishing_enabled ? 'وضع الاختبار يمنع الإرسال' : 'النشر الفعلي مفعّل'}</strong></div><span className={health?.dry_run || !health?.publishing_enabled ? 'health-dot ok' : 'health-dot warn'} /></div>
    </section>
    <div className="settings-grid">
      <section className="panel">
        <div className="panel-heading"><div><span className="section-label">البروكسيات</span><h2>{proxies?.count || 0} عناوين في proxies.txt</h2></div><Globe2 size={22} /></div>
        <p className="panel-description">التعيين ثابت لكل حساب؛ تغيير الشبكة داخل الجلسة نفسها قد يزيد طلبات التحقق بدل تقليلها.</p>
        {proxies?.proxies.length ? <div className="proxy-list">{proxies.proxies.map((proxy, index) => <div key={`${proxy.masked}-${index}`}><code dir="ltr">{proxy.masked}</code><span>{proxy.assigned_to || 'غير معيّن'}</span></div>)}</div> : <EmptyState title="لا توجد بروكسيات" description="أضف سطرًا لكل بروكسي في ملف proxies.txt ثم استخدم «تعيين تلقائي» داخل الحساب." />}
      </section>
      <section className="panel">
        <div className="panel-heading"><div><span className="section-label">الصيانة</span><h2>النسخ والتنظيف</h2></div><Archive size={22} /></div>
        <p className="panel-description">النسخة تشمل قاعدة البيانات والجلسات والقوالب، ولا تتضمن مفتاح الذكاء الاصطناعي أو الوسائط المنزلة.</p>
        <div className="maintenance-actions"><button className="btn btn-primary" disabled={busy === 'backup'} onClick={() => void createBackup()}><Archive size={17} />{busy === 'backup' ? 'جارٍ الضغط…' : 'إنشاء نسخة احتياطية'}</button>{backup && <a className="btn btn-secondary" href={backup} download><Download size={17} />تنزيل آخر نسخة</a>}<button className="btn btn-danger-quiet" disabled={busy === 'cleanup'} onClick={() => void cleanup()}><Trash2 size={17} />تنظيف ما تجاوز مدة الاحتفاظ</button></div>
        <div className="storage-paths"><div><FileKey2 size={17} /><span>الجلسات وقاعدة البيانات داخل <code>data/</code> وبصلاحيات خاصة.</span></div><div><ShieldCheck size={17} /><span>غيّر المفتاح من <code>.env</code>، وليس من قاعدة البيانات أو الواجهة.</span></div></div>
      </section>
    </div>
  </div>
}
