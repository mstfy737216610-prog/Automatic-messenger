import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Check, CheckCheck, ExternalLink, FileText, RefreshCw, RotateCcw, X } from 'lucide-react'
import { useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { EmptyState, ErrorState, Loading, PageHeader, StatusBadge } from '@/components/Common'
import { useAsync } from '@/hooks/useAsync'
import { api, formatDate, jsonOptions, platformNames } from '@/lib/api'
import type { Account, Media, Post } from '@/types'

const filters = [
  { value: 'pending_review', label: 'بانتظار المراجعة' }, { value: 'ready', label: 'جاهز' },
  { value: 'published', label: 'منشور' }, { value: 'publish_unknown', label: 'يحتاج تأكيدًا' },
  { value: 'ignored,rejected', label: 'متجاهل ومرفوض' }, { value: '', label: 'الكل' },
]

function MediaPreview({ post, media, index }: { post: Post; media: Media; index: number }) {
  const [kind, setKind] = useState<'original' | 'processed'>(media.processed_path ? 'processed' : 'original')
  const source = `/api/posts/${post.id}/media/${index}/${kind}`
  return <div className="media-preview">
    <div className="media-toolbar"><span>{media.kind === 'video' ? 'فيديو' : 'صورة'} {index + 1}</span><div><button className={kind === 'original' ? 'active' : ''} onClick={() => setKind('original')} disabled={!media.local_path}>الأصل</button><button className={kind === 'processed' ? 'active' : ''} onClick={() => setKind('processed')} disabled={!media.processed_path}>المعالج</button></div></div>
    {media.kind === 'video' ? <video src={source} controls preload="metadata" /> : <img src={source} alt={`${kind === 'processed' ? 'المعالجة' : 'الأصلية'} للمنشور ${index + 1}`} loading="lazy" />}
  </div>
}

export default function Review() {
  const [params, setParams] = useSearchParams()
  const [status, setStatus] = useState(params.get('post') ? '' : 'pending_review')
  const [account, setAccount] = useState('')
  const query = new URLSearchParams(); if (status) query.set('status', status); if (account) query.set('account_id', account)
  const { data: posts, loading, error, reload } = useAsync<Post[]>(() => api(`/api/posts?${query}`), [status, account], 20000)
  const { data: accounts } = useAsync<Account[]>(() => api('/api/accounts'), [])
  const [selectedId, setSelectedId] = useState(params.get('post') || '')
  const [text, setText] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState('')
  const selected = useMemo(() => posts?.find((post) => post.id === selectedId) || posts?.[0], [posts, selectedId])
  useEffect(() => { if (posts?.length && !selectedId) setSelectedId(posts[0].id) }, [posts, selectedId])
  useEffect(() => { setText(selected?.processed_text || selected?.raw_text || ''); setComment(selected?.user_comment || '') }, [selected?.id, selected?.processed_text, selected?.raw_text, selected?.user_comment])
  useEffect(() => { if (params.get('post') && posts?.some((post) => post.id === params.get('post'))) setSelectedId(params.get('post')!) }, [params, posts])

  const act = async (action: 'approve' | 'reject') => {
    if (!selected) return
    if (action === 'reject' && !comment.trim()) return toast.error('اكتب سبب الرفض؛ سيُستخدم في التعلم اللاحق')
    setBusy(action)
    try {
      await api(`/api/posts/${selected.id}/review`, jsonOptions('POST', { action, comment, processed_text: text }))
      toast.success(action === 'approve' ? 'اعتمدت المنشور ودخل طابور التجهيز/النشر' : 'حُفظ الرفض وسببه في ذاكرة الحساب')
      setSelectedId(''); await reload()
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : 'فشل حفظ المراجعة') }
    finally { setBusy('') }
  }
  const reprocess = async () => {
    if (!selected) return
    setBusy('reprocess')
    try { await api(`/api/posts/${selected.id}/reprocess`, jsonOptions('POST')); toast.success('أُعيد المنشور إلى معالجة الذكاء الاصطناعي'); await reload() }
    catch (reason) { toast.error(reason instanceof Error ? reason.message : 'تعذّرت إعادة المعالجة') }
    finally { setBusy('') }
  }
  const confirm = async (result: 'published' | 'failed') => {
    if (!selected) return
    setBusy(result)
    try { await api(`/api/posts/${selected.id}/confirm`, jsonOptions('POST', { status: result, note: comment })); toast.success('حُفظ تأكيدك اليدوي'); setSelectedId(''); await reload() }
    catch (reason) { toast.error(reason instanceof Error ? reason.message : 'فشل التأكيد') }
    finally { setBusy('') }
  }
  return <div className="page-stack review-page">
    <PageHeader title="مراجعة المحتوى" description="قارن الأصل بالمعالج، وعدّل النص، واكتب سبب الرفض ليصبح قاعدة تعلّم في القرارات القادمة."
      actions={<button className="btn btn-secondary" onClick={() => void reload()}><RefreshCw size={17} />تحديث</button>} />
    <div className="review-filters">
      <div className="filter-tabs" role="tablist" aria-label="حالة المنشور">{filters.map((filter) => <button role="tab" aria-selected={status === filter.value} className={status === filter.value ? 'active' : ''} key={filter.value} onClick={() => { setStatus(filter.value); setSelectedId(''); setParams({}) }}>{filter.label}</button>)}</div>
      <select aria-label="تصفية حسب الحساب" value={account} onChange={(e) => { setAccount(e.target.value); setSelectedId('') }}><option value="">كل الحسابات</option>{accounts?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
    </div>
    {loading && !posts ? <Loading /> : error && !posts ? <ErrorState message={error} retry={() => void reload()} /> : !posts?.length ? <EmptyState title="لا توجد منشورات في هذا العرض" description={status === 'pending_review' ? 'القائمة فارغة؛ لا يوجد محتوى ينتظر قرارك الآن.' : 'جرّب تغيير الحالة أو الحساب لعرض سجلات أخرى.'} /> : <div className="review-layout">
      <aside className="review-list" aria-label="قائمة المنشورات">
        {posts.map((post) => <button key={post.id} className={selected?.id === post.id ? 'selected' : ''} onClick={() => setSelectedId(post.id)}>
          <div><strong>{post.account_name}</strong><StatusBadge status={post.status} /></div><p>{post.processed_text || post.raw_text || 'منشور وسائط دون نص'}</p><span>{platformNames[post.platform || '']} · {post.source_handle || post.author} · {formatDate(post.created_at)}</span>
        </button>)}
      </aside>
      {selected && <article className="review-detail">
        <header className="review-detail-head"><div><span className="section-label">{selected.account_name} · {platformNames[selected.platform || '']}</span><h2>من {selected.source_handle || selected.author || 'مصدر'}</h2></div><a className="icon-btn" href={selected.url} target="_blank" rel="noreferrer" aria-label="فتح المنشور الأصلي"><ExternalLink size={19} /></a></header>
        <div className="ai-decision">
          <div><span>قرار الفلترة</span><strong>{selected.ai_decision === 'publish' ? 'نشر مقترح' : selected.ai_decision === 'ignore' ? 'تجاهل مقترح' : 'مراجعة بشرية'}</strong></div>
          {typeof selected.ai_confidence === 'number' && <div className="confidence"><span>الثقة</span><strong>{Math.round(selected.ai_confidence * 100)}٪</strong></div>}
          <p>{selected.ai_reason || 'لم يُسجل سبب بعد.'}</p>
        </div>
        {(selected.error || selected.status === 'publish_unknown') && <div className="inline-alert warning" role="alert"><AlertTriangle size={18} /><span>{selected.error || 'تحقق من المنصة ثم سجّل النتيجة يدويًا.'}</span></div>}
        {selected.media.length > 0 && <div className="media-grid">{selected.media.map((media, index) => <MediaPreview key={`${selected.id}-${index}`} post={selected} media={media} index={index} />)}</div>}
        <details className="original-text"><summary><FileText size={17} />عرض النص الأصلي</summary><p>{selected.raw_text || 'لا يوجد نص أصلي؛ راجع الوسائط.'}</p></details>
        <label className="field"><span>النص النهائي للنشر</span><textarea className="post-editor" rows={8} value={text} onChange={(e) => setText(e.target.value)} placeholder="اكتب النص الذي سيظهر على القالب وفي المنشور" /></label>
        <label className="field"><span>تعليقك / سبب القرار</span><textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="مثال: هذا إعلان لمقهى بعيد عن الجامعة، استبعد هذا النوع" /></label>
        {selected.status === 'publish_unknown' ? <div className="review-actions confirm-actions"><p>افتح حساب المنصة وتأكد هل وصل المنشور فعلًا، ثم اختر النتيجة. لا تعِد النشر قبل ذلك.</p><div><button className="btn btn-secondary" disabled={busy === 'failed'} onClick={() => void confirm('failed')}><X size={17} />لم يُنشر</button><button className="btn btn-primary" disabled={busy === 'published'} onClick={() => void confirm('published')}><CheckCheck size={17} />تأكد نشره</button></div></div> : <div className="review-actions">
          <button className="btn btn-quiet" disabled={busy === 'reprocess'} onClick={() => void reprocess()}><RotateCcw size={17} />إعادة الفلترة</button>
          <div><button className="btn btn-danger-quiet" disabled={busy === 'reject' || ['published', 'ignored', 'rejected'].includes(selected.status)} onClick={() => void act('reject')}><X size={17} />{busy === 'reject' ? 'جارٍ الحفظ…' : 'رفض وتعلّم'}</button><button className="btn btn-primary" disabled={busy === 'approve' || selected.status === 'published'} onClick={() => void act('approve')}><Check size={17} />{busy === 'approve' ? 'جارٍ الاعتماد…' : 'اعتماد وتجهيز'}</button></div>
        </div>}
      </article>}
    </div>}
  </div>
}
