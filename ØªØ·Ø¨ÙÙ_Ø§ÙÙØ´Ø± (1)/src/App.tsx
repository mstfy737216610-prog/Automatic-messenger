import { Navigate, Route, Routes } from 'react-router'
import Layout from '@/components/Layout'
import Accounts from '@/pages/Accounts'
import ActivityPage from '@/pages/Activity'
import Assistant from '@/pages/Assistant'
import Dashboard from '@/pages/Dashboard'
import Review from '@/pages/Review'
import SettingsPage from '@/pages/Settings'
import './App.css'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="accounts" element={<Accounts />} />
        <Route path="review" element={<Review />} />
        <Route path="assistant" element={<Assistant />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
