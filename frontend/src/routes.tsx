import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/layout/app-shell'
import { ProtectedRoute } from '@/components/layout/protected-route'
import { LoginPage } from '@/pages/login'
import { DashboardPage } from '@/pages/dashboard'
import { ProfilePage } from '@/pages/profile'
import { ResearchPage } from '@/pages/research'
import { SearchPage } from '@/pages/search'
import { GmailPage } from '@/pages/gmail'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppShell />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'profile', element: <ProfilePage /> },
      { path: 'research', element: <ResearchPage /> },
      { path: 'search', element: <SearchPage /> },
      { path: 'gmail', element: <GmailPage /> },
    ],
  },
])
