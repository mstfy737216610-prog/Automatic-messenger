import { useEffect, useState } from 'react'
import { Activity, Bot, Inbox, LayoutDashboard, Settings, UsersRound } from 'lucide-react'
import { NavLink, Outlet } from 'react-router'
import { api } from '@/lib/api'
import type { Health } from '@/types'

const navItems = [
  { to: '/', label: 'الرئيسية', icon: LayoutDashboard },
  { to: '/accounts', label: 'الحسابات', icon: UsersRound },
  { to: '/review', label: 'المراجعة', icon: Inbox },
  { to: '/assistant', label: 'المساعد', icon: Bot },
  { to: '/activity', label: 'النشاط', icon: Activity },
]

export default function Layout() {
  const [health, setHealth] = useState<Health | null>(null)
  useEffect(() => { api<Health>('/api/health').then(setHealth).catch(() => setHealth(null)) }, [])
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">انتقل إلى المحتوى</a>
    <aside className="sidebar">
      <NavLink to="/" className="brand" aria-label="مرسال — الرئيسية">
        <span className="brand-mark">م</span><span><strong>مرسال</strong><small>غرفة عمليات النشر</small></span>
      </NavLink>
      <nav className="side-nav" aria-label="التنقل الرئيسي">
        {navItems.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => isActive ? 'active' : ''}><Icon size={20} /><span>{label}</span></NavLink>)}
        <NavLink to="/settings" className={({ isActive }) => isActive ? 'active' : ''}><Settings size={20} /><span>الإعدادات</span></NavLink>
      </nav>
      <div className="sidebar-foot"><span className="live-dot" /><span>التخزين محلي على هذا الجهاز</span><small>الإصدار {health?.version || '—'}</small></div>
    </aside>
    <div className="workspace">
      <header className="topbar">
        <div><span className="live-dot" /><strong>{health?.dry_run || !health?.publishing_enabled ? 'وضع الاختبار' : 'النشر الفعلي مفعّل'}</strong><span className="topbar-detail">{health?.dry_run || !health?.publishing_enabled ? 'لن يُرسل أي منشور للمنصات' : 'تحقق من كل عملية'}</span></div>
        <NavLink to="/settings" className="icon-btn" aria-label="الإعدادات"><Settings size={20} /></NavLink>
      </header>
      <main id="main-content" className="main-content"><Outlet /></main>
    </div>
    <nav className="mobile-nav" aria-label="التنقل على الهاتف">
      {navItems.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => isActive ? 'active' : ''}><Icon size={21} /><span>{label}</span></NavLink>)}
    </nav>
  </div>
}
