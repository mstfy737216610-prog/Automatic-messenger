import { useEffect, useMemo, useRef, useState } from 'react'
import { Bot, Check, ChevronLeft, FileKey2, ImagePlus, Link2, Plus, Radar, RefreshCw, ShieldCheck, Trash2, UserRound, WandSparkles } from 'lucide-react'
import { toast } from 'sonner'
import { EmptyState, ErrorState, Field, Loading, Modal, PageHeader, Toggle } from '@/components/Common'
import { useAsync } from '@/hooks/useAsync'
import { api, formatDate, jsonOptions, platformNames, sessionNames } from '@/lib/api'
import type { Account, Platform, Source } from '@/types'

type FormState = {
  name: string; platform: Platform; username: string; proxy: string; clearProxy: boolean
  phone: string; interval: number; minDelay: number; maxDelay: number
  review: boolean; auto: boolean; enabled: boolean; templateMode: string
  background: string; textColor: string; accent: string; telegramTarget: string
  replaceUsername: boolean; ocr: boolean
}
const blankForm: FormState = {
  name: '', platform: 'x', username: '', proxy: '', clearProxy: false, phone: '', interval: 900,
  minDelay: 45, maxDelay: 180, review: true, auto: false, enabled: false, templateMode: 'rebuild',
  background: '#f4f6f2', textColor: '#18201c', accent: '#008f6d', telegramTarget: '', replaceUsername: true, ocr: true,
}
const fromAccount = (account: Account): FormState => ({
  name: account.name, platform: account.platform, username: account.username, proxy: '', clearProxy: false,
  phone: account.phone_replacement, interval: account.monitor_interval_sec, minDelay: account.min_delay_sec,
  maxDelay: account.max_delay_sec, review: account.review_required, auto: account.auto_publish, enabled: account.enabled,
  templateMode: account.settings.template?.mode || 'rebuild', background: account.settings.template?.background || '#f4f6f2',
  textColor: account.settings.template?.text || '#18201c', accent: account.settings.template?.accent || '#008f6d',
  telegramTarget: account.settings.telegram_target_url || '', replaceUsername: account.settings.replace_username ?? true,
  ocr: account.settings.ocr_images ?? true,
})

export default function Accounts() {
  const { data: accounts, loading, error, reload } = useAsync<Account[]>(() => api('/api/accounts'), [], 25000)
  const [selectedId, setSelectedId] = useState('')
  const [modal, setModal] = useState<'new' | 'edit' | 'delete' | null>(null)
  const [form, setForm] = useState<FormState>(blankForm)
  const [saving, setSaving] = useState(false)
  const [busy, setBusy] = useState('')
  const [preview, setPreview] = useState('')
  const [source, setSource] = useState({ platform: 'x' as Source['platform'], handle: '', url: '' })
  const cookieInput = useRef<HTMLInputElement>(null)
  const selected = useMemo(() => accounts?.find((account) => account.id === selectedId) || accounts?.[0], [accounts, selectedId])
  useEffect(() => { if (accounts?.length && !selectedId) setSelectedId(accounts[0].id) }, [accounts, selectedId])
  useEffect(() => { setPreview('') }, [selected?.id])

  const saveAccount = async (event: React.FormEvent) => {
    event.preventDefault()
    if (form.maxDelay < form.minDelay) return toast.error('أقصى تأخير يجب ألا يقل عن أدنى تأخير')
    setSaving(true)
    const oldSettings = modal === 'edit' && selected ? selected.settings : {}
    const payload: Record<string, unknown> = {
      name: form.name, platform: form.platform, username: form.username, phone_replacement: form.phone,
      monitor_interval_sec: form.interval, min_delay_sec: form.minDelay, max_delay_sec: form.maxDelay,
      review_required: form.review, auto_publish: form.auto, enabled: form.enabled,
      settings: {
        ...oldSettings, telegram_target_url: form.telegramTarget, replace_username: form.replaceUsername, ocr_images: form.ocr,
        template: { ...(oldSettings.template || {}), mode: form.templateMode, background: form.background, text: form.textColor, accent: form.accent },
      },
    }
    if (form.proxy) payload.proxy_url = form.proxy
    if (modal === 'edit' && form.clearProxy) payload.proxy_url = null
    try {
      const result = await api<Account>(modal === 'edit' && selected ? `/api/accounts/${selected.id}` : '/api/accounts', jsonOptions(modal === 'edit' ? 'PATCH' : 'POST', payload))
      toast.success(modal === 'edit' ? 'حُفظت إعدادات الحساب' : 'أُضيف الحساب؛ اربط جلسته ومصادره الآن')
      setSelectedId(result.id); setModal(null); await reload()
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : 'تعذّر حفظ الحساب') }
    finally { setSaving(false) }
  }
  const patch = async (path: string, body: unknown, message: string) => {
    try { await api(path, jsonOptions('PATCH', body)); toast.success(message); await reload(true) }
    catch (reason) { toast.error(reason instanceof Error ? reason.message : 'فشل التحديث') }
  }
  const action = async (key: string, fn: () => Promise<void>) => {
    setBusy(key)
    try { await fn() } catch (reason) { toast.error(reason instanceof Error ? reason.message : 'فشل الإجراء') }
    finally { setBusy(''); await reload(true) }
  }
  const addSource = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!selected) return
    await action('source', async () => {
      await api(`/api/accounts/${selected.id}/sources`, jsonOptions('POST', source))
      setSource({ platform: 'x', handle: '', url: '' }); toast.success('أُضيف المصدر')
    })
  }
  const upload = async (file: File, kind: 'cookies' | 'logo' | 'template') => {
    if (!selected) return
    const body = new FormData(); body.append('file', file)
    await action(kind, async () => {
      if (kind === 'cookies') await api(`/api/accounts/${selected.id}/cookies`, { method: 'POST', body })
      else { body.append('kind', kind); await api(`/api/accounts/${selected.id}/assets`, { method: 'POST', body }) }
      toast.success(kind === 'cookies' ? 'استُوردت الجلسة؛ افحصها قبل التفعيل' : 'حُفظت الصورة داخل مساحة الحساب')
    })
  }
  if (loading && !accounts) return <Loading />
  if (error && !accounts) return <ErrorState message={error} retry={() => void reload()} />
  return <div className="page-stack">
    <PageHeader title="الحسابات والمصادر" description="لكل حساب جلسة وبروكسي وذاكرة وقوالب مستقلة؛ ابدأ بحساب واحد واختبره جيدًا."
      actions={<button className="btn btn-primary" onClick={() => { setForm(blankForm); setModal('new') }}><Plus size={18} />إضافة حساب</button>} />
    {!accounts?.length ? <EmptyState title="لا توجد حسابات بعد" description="الحساب هنا هو وجهة النشر، وليس الحساب الذي تراقبه. ستضيف المصادر في الخطوة التالية."
      action={<button className="btn btn-primary" onClick={() => { setForm(blankForm); setModal('new') }}><Plus size={18} />إنشاء أول حساب</button>} /> : <div className="accounts-layout">
      <aside className="account-selector" aria-label="حسابات الوجهة">
        {accounts.map((account) => <button key={account.id} className={selected?.id === account.id ? 'selected' : ''} onClick={() => setSelectedId(account.id)}>
          <span className={`platform-letter platform-${account.platform}`}>{platformNames[account.platform].slice(0, 1)}</span>
          <span><strong>{account.name}</strong><small>{platformNames[account.platform]} · {account.sources?.length || 0} مصادر</small></span>
          <ChevronLeft size={17} />
        </button>)}
      </aside>
      {selected && <div className="account-detail">
        <section className="account-hero">
          <div className="account-title"><span className={`platform-letter platform-${selected.platform}`}>{platformNames[selected.platform].slice(0, 1)}</span><div><span className="section-label">{platformNames[selected.platform]}</span><h2>{selected.name}</h2><p>{selected.username ? `@${selected.username.replace(/^@/, '')}` : 'دون اسم مستخدم محفوظ'}</p></div></div>
          <div className="account-toggle"><span>{selected.enabled ? 'المراقبة مفعّلة' : 'الحساب متوقف'}</span><Toggle checked={selected.enabled} label={selected.enabled ? 'إيقاف الحساب' : 'تشغيل الحساب'} onChange={(enabled) => void patch(`/api/accounts/${selected.id}`, { enabled }, enabled ? 'شُغّل الحساب' : 'توقف الحساب')} /></div>
        </section>
        <div className="account-actions">
          <button className="btn btn-primary" disabled={busy === 'monitor'} onClick={() => void action('monitor', async () => { await api(`/api/accounts/${selected.id}/monitor`, jsonOptions('POST')); toast.success('دخل الفحص إلى الطابور') })}><Radar size={17} />فحص الآن</button>
          <button className="btn btn-secondary" disabled={busy === 'session'} onClick={() => void action('session', async () => { const result = await api<{ detail: string }>(`/api/accounts/${selected.id}/check-session`, jsonOptions('POST')); toast.info(result.detail) })}><ShieldCheck size={17} />فحص الجلسة</button>
          <button className="btn btn-secondary" onClick={() => { setForm(fromAccount(selected)); setModal('edit') }}><UserRound size={17} />الإعدادات</button>
          <button className="btn btn-danger-quiet" onClick={() => setModal('delete')}><Trash2 size={17} />حذف</button>
        </div>
        {selected.last_error && <div className="inline-alert" role="alert">{selected.last_error}</div>}
        <section className="detail-grid">
          <div className="detail-section">
            <div className="section-heading"><div><span className="section-label">الوصول والعزل</span><h3>الجلسة والبروكسي</h3></div></div>
            <dl className="facts"><div><dt>الجلسة</dt><dd>{sessionNames[selected.session_status] || selected.session_status}</dd></div><div><dt>البروكسي</dt><dd dir="ltr">{selected.proxy_masked || 'الاتصال المباشر'}</dd></div><div><dt>آخر فحص</dt><dd>{formatDate(selected.last_monitor_at)}</dd></div></dl>
            <input ref={cookieInput} type="file" accept=".json,application/json" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file, 'cookies'); event.target.value = '' }} />
            <div className="button-row"><button className="btn btn-secondary" onClick={() => cookieInput.current?.click()}><FileKey2 size={17} />استيراد Cookies</button><button className="btn btn-quiet" disabled={busy === 'proxy'} onClick={() => void action('proxy', async () => { await api(`/api/accounts/${selected.id}/proxy/auto`, jsonOptions('POST')); toast.success('عُيّن بروكسي ثابت') })}><Link2 size={17} />تعيين تلقائي</button></div>
          </div>
          <div className="detail-section">
            <div className="section-heading"><div><span className="section-label">الهوية البصرية</span><h3>القالب والشعار</h3></div></div>
            <div className="asset-buttons">
              {(['logo', 'template'] as const).map((kind) => <label className="btn btn-secondary" key={kind}><ImagePlus size={17} />{kind === 'logo' ? 'رفع الشعار' : 'رفع خلفية القالب'}<input type="file" accept="image/png,image/jpeg,image/webp" aria-label={kind === 'logo' ? 'رفع الشعار' : 'رفع خلفية القالب'} onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file, kind); event.target.value = '' }} /></label>)}
            </div>
            <button className="btn btn-quiet" disabled={busy === 'preview'} onClick={() => void action('preview', async () => { const result = await api<{ preview_url: string }>(`/api/accounts/${selected.id}/template-preview`, jsonOptions('POST')); setPreview(result.preview_url); toast.success('أُنشئت معاينة عربية فعلية') })}><WandSparkles size={17} />إنشاء معاينة</button>
            {preview && <img className="template-preview" src={preview} alt="معاينة القالب النصي بشعار الحساب" />}
          </div>
        </section>
        <section className="detail-section sources-section">
          <div className="section-heading"><div><span className="section-label">قائمة المراقبة</span><h3>المصادر ({selected.sources?.length || 0})</h3></div><span className="muted-text">الفحص كل {Math.round(selected.monitor_interval_sec / 60)} دقيقة</span></div>
          {selected.sources?.length ? <div className="source-list">{selected.sources.map((item) => <div className="source-row" key={item.id}>
            <div><strong>{item.handle}</strong><a href={item.url} target="_blank" rel="noreferrer" dir="ltr">{item.url}</a>{item.last_error && <small className="error-text">{item.last_error}</small>}</div>
            <span className="source-platform">{platformNames[item.platform]}</span>
            <Toggle checked={item.enabled} label={`${item.enabled ? 'تعطيل' : 'تفعيل'} المصدر ${item.handle}`} onChange={(enabled) => void patch(`/api/sources/${item.id}`, { enabled }, 'حُدّث المصدر')} />
            <button className="icon-btn danger-icon" aria-label={`حذف المصدر ${item.handle}`} onClick={() => void action(`delete-${item.id}`, async () => { await api(`/api/sources/${item.id}`, { method: 'DELETE' }); toast.success('حُذف المصدر') })}><Trash2 size={17} /></button>
          </div>)}</div> : <p className="empty-inline">لا توجد مصادر؛ أضف حسابًا واحدًا لمراقبته أولًا.</p>}
          <form className="source-form" onSubmit={(event) => void addSource(event)}>
            <select aria-label="منصة المصدر" value={source.platform} onChange={(e) => setSource({ ...source, platform: e.target.value as Source['platform'] })}><option value="x">إكس</option><option value="instagram">إنستغرام</option><option value="tiktok">تيك توك</option></select>
            <input required minLength={1} aria-label="معرف المصدر" placeholder="معرف الحساب دون @" value={source.handle} onChange={(e) => setSource({ ...source, handle: e.target.value })} />
            <input required type="url" dir="ltr" aria-label="رابط المصدر" placeholder="https://…" value={source.url} onChange={(e) => setSource({ ...source, url: e.target.value })} />
            <button className="btn btn-primary" disabled={busy === 'source'}><Plus size={17} />إضافة</button>
          </form>
        </section>
        <section className="detail-section learning-section"><div><span className="section-label">ذاكرة الحساب</span><h3>اللهجة والموضوعات</h3><p>{selected.profile?.dialect || 'لم يُبنَ ملف النمط بعد. تحتاج بعض المنشورات ثم يمكن توليده من السجل.'}</p></div><button className="btn btn-secondary" disabled={busy === 'profile'} onClick={() => void action('profile', async () => { await api(`/api/accounts/${selected.id}/profile/rebuild`, jsonOptions('POST')); toast.success('حُدّث ملف النمط') })}><Bot size={17} />تحليل النمط</button></section>
      </div>}
    </div>}

    <Modal open={modal === 'new' || modal === 'edit'} onOpenChange={(open) => !open && setModal(null)} title={modal === 'edit' ? `إعدادات ${selected?.name}` : 'حساب وجهة جديد'} description="لن يبدأ النشر التلقائي إلا إذا أوقفت المراجعة وفعّلت الخيار صراحة." wide>
      <form className="form-stack" onSubmit={(event) => void saveAccount(event)}>
        <div className="form-grid two">
          <Field label="اسم الحساب داخل النظام"><input required autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="مثال: أخبار الجامعة" /></Field>
          <Field label="المنصة"><select disabled={modal === 'edit'} value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value as Platform })}><option value="x">إكس</option><option value="instagram">إنستغرام</option><option value="tiktok">تيك توك</option><option value="telegram">تيليجرام</option></select></Field>
          <Field label="اسم المستخدم للنشر"><input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="دون @" /></Field>
          <Field label="رقمك البديل للمساعدة الطلابية" hint="لا يُستبدل إلا عند تصنيف المنشور كمساعدة أو قروبات طلابية"><input dir="ltr" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="+9665…" /></Field>
          <Field label="بروكسي ثابت" hint={modal === 'edit' ? `اتركه فارغًا للإبقاء: ${selected?.proxy_masked || 'مباشر'}` : 'HTTP أو SOCKS5؛ بيانات الدخول لا تظهر لاحقًا'}><input dir="ltr" value={form.proxy} onChange={(e) => setForm({ ...form, proxy: e.target.value })} placeholder="socks5://user:pass@host:port" /></Field>
          {modal === 'edit' && <label className="check-field"><input type="checkbox" checked={form.clearProxy} onChange={(e) => setForm({ ...form, clearProxy: e.target.checked })} /><span>إزالة البروكسي الحالي</span></label>}
          <Field label="فترة فحص المصادر (ثانية)"><input type="number" min={60} max={86400} value={form.interval} onChange={(e) => setForm({ ...form, interval: Number(e.target.value) })} /></Field>
          <div className="form-grid two compact"><Field label="أدنى تأخير"><input type="number" min={0} value={form.minDelay} onChange={(e) => setForm({ ...form, minDelay: Number(e.target.value) })} /></Field><Field label="أقصى تأخير"><input type="number" min={0} value={form.maxDelay} onChange={(e) => setForm({ ...form, maxDelay: Number(e.target.value) })} /></Field></div>
          {form.platform === 'telegram' && <Field label="رابط محادثة Telegram Web"><input type="url" dir="ltr" value={form.telegramTarget} onChange={(e) => setForm({ ...form, telegramTarget: e.target.value })} placeholder="https://web.telegram.org/a/#…" /></Field>}
        </div>
        <fieldset className="form-fieldset"><legend>المعالجة والهوية</legend><div className="form-grid three">
          <Field label="معالجة الصور"><select value={form.templateMode} onChange={(e) => setForm({ ...form, templateMode: e.target.value })}><option value="rebuild">إعادة بناء النص على قالبي</option><option value="overlay">الإبقاء على الصورة وإضافة الشعار</option></select></Field>
          <Field label="الخلفية"><input type="color" value={form.background} onChange={(e) => setForm({ ...form, background: e.target.value })} /></Field>
          <Field label="النص"><input type="color" value={form.textColor} onChange={(e) => setForm({ ...form, textColor: e.target.value })} /></Field>
          <Field label="اللون المميز"><input type="color" value={form.accent} onChange={(e) => setForm({ ...form, accent: e.target.value })} /></Field>
        </div><div className="checks-grid"><label className="check-field"><input type="checkbox" checked={form.ocr} onChange={(e) => setForm({ ...form, ocr: e.target.checked })} /><span>استخراج النص العربي من الصور</span></label><label className="check-field"><input type="checkbox" checked={form.replaceUsername} onChange={(e) => setForm({ ...form, replaceUsername: e.target.checked })} /><span>استبدال معرف المصدر بمعرفي في النص</span></label></div></fieldset>
        <fieldset className="form-fieldset"><legend>سياسة القرار</legend><div className="checks-grid"><label className="check-field"><input type="checkbox" checked={form.review} onChange={(e) => setForm({ ...form, review: e.target.checked })} /><span>المراجعة البشرية مطلوبة</span></label><label className="check-field"><input type="checkbox" checked={form.auto} onChange={(e) => setForm({ ...form, auto: e.target.checked })} /><span>السماح بالنشر التلقائي عالي الثقة</span></label><label className="check-field"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /><span>تشغيل المراقبة</span></label></div>{form.auto && !form.review && <p className="warning-text">تنبيه: سينشر النظام تلقائيًا فقط عند تجاوز عتبة الثقة، وبعد إيقاف وضع الاختبار من .env.</p>}</fieldset>
        <div className="modal-actions"><button type="button" className="btn btn-quiet" onClick={() => setModal(null)}>إلغاء</button><button className="btn btn-primary" disabled={saving}>{saving ? <RefreshCw className="spin" size={17} /> : <Check size={17} />}{saving ? 'جارٍ الحفظ…' : 'حفظ الحساب'}</button></div>
      </form>
    </Modal>
    <Modal open={modal === 'delete'} onOpenChange={(open) => !open && setModal(null)} title={`حذف ${selected?.name}؟`} description="سيُحذف الحساب وسجلاته وجلسته، مع إنشاء أرشيف أمان مضغوط قبل الحذف.">
      <div className="modal-actions"><button className="btn btn-quiet" onClick={() => setModal(null)}>تراجع</button><button className="btn btn-danger" disabled={busy === 'delete'} onClick={() => void action('delete', async () => { if (!selected) return; const result = await api<{ safety_archive: string }>(`/api/accounts/${selected.id}`, { method: 'DELETE' }); toast.success(`حُذف الحساب؛ أرشيف الأمان: ${result.safety_archive}`); setSelectedId(''); setModal(null) })}><Trash2 size={17} />حذف نهائي</button></div>
    </Modal>
  </div>
}
