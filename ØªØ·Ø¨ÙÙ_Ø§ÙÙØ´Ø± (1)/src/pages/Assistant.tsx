import { useEffect, useState } from 'react'
import { Bot, Check, FlaskConical, ListRestart, Send, Settings2, ShieldAlert } from 'lucide-react'
import { toast } from 'sonner'
import { EmptyState, ErrorState, Field, Loading, PageHeader } from '@/components/Common'
import { useAsync } from '@/hooks/useAsync'
import { api, formatDate, jsonOptions } from '@/lib/api'
import type { Account, AIConfig, AITestResult, ChatMessage } from '@/types'

export default function Assistant() {
  const [account, setAccount] = useState('')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const { data: accounts } = useAsync<Account[]>(() => api('/api/accounts'), [])
  const { data: chat, loading, reload } = useAsync<ChatMessage[]>(() => api(`/api/chat${account ? `?account_id=${account}` : ''}`), [account])
  const { data: config, loading: configLoading, error, reload: reloadConfig } = useAsync<AIConfig>(() => api('/api/ai/config'), [])
  const [aiForm, setAiForm] = useState({ base_url: '', model: '', timeout_seconds: 60 })
  const [models, setModels] = useState<string[]>([])
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<AITestResult | null>(null)
  useEffect(() => { if (config) setAiForm({ base_url: config.base_url, model: config.model, timeout_seconds: config.timeout_seconds }) }, [config])
  const send = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!message.trim()) return
    setSending(true)
    try {
      const result = await api<{ reply: string }>('/api/chat', jsonOptions('POST', { account_id: account || null, message }))
      setMessage(''); toast.success(result.reply); await reload()
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : 'تعذّر حفظ التعليمة') }
    finally { setSending(false) }
  }
  const loadModels = async () => {
    setTesting(true)
    try { const result = await api<{ models: string[] }>('/api/ai/models'); setModels(result.models); toast.success(`وصلت قائمة تضم ${result.models.length} نموذجًا`) }
    catch (reason) { toast.error(reason instanceof Error ? reason.message : 'تعذّر جلب النماذج') }
    finally { setTesting(false) }
  }
  const saveConfig = async (event: React.FormEvent) => {
    event.preventDefault(); setTesting(true)
    try { await api('/api/ai/config', jsonOptions('PATCH', aiForm)); toast.success('حُفظت إعدادات النموذج'); await reloadConfig() }
    catch (reason) { toast.error(reason instanceof Error ? reason.message : 'تعذّر حفظ الإعدادات') }
    finally { setTesting(false) }
  }
  const test = async () => {
    setTesting(true); setTestResult(null)
    try {
      const result = await api<AITestResult>('/api/ai/test', jsonOptions('POST', { model: aiForm.model }))
      setTestResult(result)
      if (result.ok) toast.success('استجاب النموذج بـ JSON صالح')
      else toast.warning('وصل رد غير متوقع')
    }
    catch (reason) { toast.error(reason instanceof Error ? reason.message : 'فشل اختبار النموذج') }
    finally { setTesting(false) }
  }
  return <div className="page-stack">
    <PageHeader title="المساعد وقواعد التعلّم" description="اكتب ما تريد استبعاده أو تنبيهك له؛ تُحفظ التعليمة محليًا وتدخل في سياق الفلترة دون تدريب نموذج." />
    <div className="assistant-grid">
      <section className="panel chat-panel">
        <div className="panel-heading"><div><span className="section-label">شات التعليمات</span><h2>ما الذي يجب تغييره؟</h2></div><select aria-label="نطاق التعليمة" value={account} onChange={(e) => setAccount(e.target.value)}><option value="">قاعدة عامة لكل الحسابات</option>{accounts?.map((item) => <option key={item.id} value={item.id}>خاص بـ {item.name}</option>)}</select></div>
        <div className="safety-note"><ShieldAlert size={19} /><p>اكتب قواعد واضحة قابلة للاختبار. مثال: «استبعد إعلانات الكافيهات حتى لو وردت داخل صورة، وأوقف أي إعلان لا يخص الجامعة للمراجعة».</p></div>
        <div className="chat-log" aria-live="polite">
          {loading && !chat ? <Loading label="جارٍ فتح سجل التعليمات…" /> : chat?.length ? chat.map((item) => <div className={`chat-message chat-${item.role}`} key={item.id}><span>{item.role === 'user' ? 'أنت' : 'مرسال'} · {formatDate(item.created_at)}</span><p>{item.text}</p></div>) : <EmptyState title="لا توجد تعليمات في هذا النطاق" description="أرسل أول قاعدة، ثم راقب أثرها في صفحة المراجعة." />}
        </div>
        <form className="chat-form" onSubmit={(event) => void send(event)}><textarea required rows={3} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="اكتب تعليمة جديدة للنظام…" aria-label="التعليمة" /><button className="btn btn-primary" disabled={sending}><Send size={17} />{sending ? 'جارٍ الحفظ…' : 'حفظ كقاعدة'}</button></form>
      </section>
      <section className="panel ai-panel">
        <div className="panel-heading"><div><span className="section-label">مزوّد الذكاء الاصطناعي</span><h2>النموذج والاتصال</h2></div><Settings2 size={22} /></div>
        {configLoading && !config ? <Loading /> : error && !config ? <ErrorState message={error} retry={() => void reloadConfig()} /> : <form className="form-stack" onSubmit={(event) => void saveConfig(event)}>
          <div className={`key-status ${config?.key_configured ? 'configured' : 'missing'}`}><span className="live-dot" />{config?.key_configured ? 'المفتاح مضبوط في بيئة التشغيل' : 'المفتاح غير مضبوط؛ عدّل .env'}</div>
          <Field label="عنوان الخدمة الأساسي"><input required type="url" dir="ltr" value={aiForm.base_url} onChange={(e) => setAiForm({ ...aiForm, base_url: e.target.value })} /></Field>
          <Field label="النموذج" hint="auto أثبت نجاحه في اختبار الاتصال؛ يمكنك اختيار نموذج صريح واختباره.">
            <div className="input-with-datalist"><input required list="ai-models" dir="ltr" value={aiForm.model} onChange={(e) => setAiForm({ ...aiForm, model: e.target.value })} /><datalist id="ai-models">{models.map((model) => <option key={model} value={model} />)}</datalist></div>
          </Field>
          <Field label="مهلة الاستجابة (ثانية)"><input type="number" min={5} max={300} value={aiForm.timeout_seconds} onChange={(e) => setAiForm({ ...aiForm, timeout_seconds: Number(e.target.value) })} /></Field>
          <div className="button-row"><button type="button" className="btn btn-secondary" disabled={testing} onClick={() => void loadModels()}><ListRestart size={17} />جلب النماذج</button><button type="button" className="btn btn-secondary" disabled={testing} onClick={() => void test()}><FlaskConical size={17} />اختبار الرد</button></div>
          {testResult && <div className="test-result" role="status"><Check size={18} /><div><strong>نجح الاتصال خلال {testResult.seconds} ثانية</strong><span>النموذج الفعلي: {testResult.resolved_model || testResult.requested_model}</span></div></div>}
          <button className="btn btn-primary" disabled={testing}><Check size={17} />حفظ إعدادات النموذج</button>
        </form>}
        <div className="ai-explainer"><Bot size={20} /><p>عند انقطاع المزوّد لا يتحول الفشل إلى «نشر» أو «تجاهل». يبقى المحتوى في المراجعة حتى تقرر أنت.</p></div>
      </section>
    </div>
  </div>
}
