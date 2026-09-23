import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/layout/app-shell'
import { ProtectedRoute } from '@/components/layout/protected-route'
import { LandingRoute } from '@/features/landing/route'
import { LoginPage } from '@/pages/login'
import { DashboardPage } from '@/pages/dashboard'
import { ProfilePage } from '@/pages/profile'
import { ResearchPage } from '@/pages/research'
import { SearchPage } from '@/pages/search'
import { GmailPage } from '@/pages/gmail'
import { GithubPage } from '@/pages/github'
import { CalendarPage } from '@/pages/calendar'
import { IntegrationsPage } from '@/pages/integrations'
import { CareerPage } from '@/pages/career'
import { ApplicationsPage } from '@/pages/applications'
import { DigestPage } from '@/pages/digest'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <LandingRoute />,
  },
  { path: '/login', element: <LoginPage /> },
  {
    element: (
      <ProtectedRoute>
        <AppShell />
      </ProtectedRoute>
    ),
    children: [
      { path: 'dashboard', element: <DashboardPage /> },
      { path: 'profile', element: <ProfilePage /> },
      { path: 'research', element: <ResearchPage /> },
      { path: 'search', element: <SearchPage /> },
      { path: 'gmail', element: <GmailPage /> },
      { path: 'career', element: <CareerPage /> },
      { path: 'applications', element: <ApplicationsPage /> },
      { path: 'integrations', element: <IntegrationsPage /> },
      { path: 'github', element: <GithubPage /> },
      { path: 'calendar', element: <CalendarPage /> },
      { path: 'digest', element: <DigestPage /> },
    ],
  },
])
