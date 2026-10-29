import type { ReactNode } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { AlertCircle, Inbox, LoaderCircle, X } from 'lucide-react'
import { statusNames } from '@/lib/api'

export function PageHeader({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return <header className="page-header">
    <div><h1>{title}</h1><p>{description}</p></div>
    {actions && <div className="page-actions">{actions}</div>}
  </header>
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`status status-${status}`}>{statusNames[status] || status}</span>
}

export function Loading({ label = 'جارٍ تحميل البيانات…' }: { label?: string }) {
  return <div className="state-block" role="status"><LoaderCircle className="spin" size={25} /><p>{label}</p></div>
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="state-block error-state" role="alert"><AlertCircle size={25} /><p>{message}</p>{retry && <button className="btn btn-secondary" onClick={retry}>إعادة المحاولة</button>}</div>
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="state-block"><Inbox size={28} /><h3>{title}</h3><p>{description}</p>{action}</div>
}

export function Modal({ open, onOpenChange, title, description, children, wide = false }: {
  open: boolean; onOpenChange: (open: boolean) => void; title: string; description?: string; children: ReactNode; wide?: boolean
}) {
  return <Dialog.Root open={open} onOpenChange={onOpenChange}>
    <Dialog.Portal>
      <Dialog.Overlay className="modal-overlay" />
      <Dialog.Content className={`modal-content ${wide ? 'modal-wide' : ''}`} dir="rtl">
        <div className="modal-heading">
          <div><Dialog.Title>{title}</Dialog.Title>{description && <Dialog.Description>{description}</Dialog.Description>}</div>
          <Dialog.Close className="icon-btn" aria-label="إغلاق"><X size={20} /></Dialog.Close>
        </div>
        {children}
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
}

export function Toggle({ checked, onChange, label, disabled = false }: { checked: boolean; onChange: (value: boolean) => void; label: string; disabled?: boolean }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} className={`toggle ${checked ? 'is-on' : ''}`}
    onClick={() => onChange(!checked)} disabled={disabled}><span /></button>
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>
}
