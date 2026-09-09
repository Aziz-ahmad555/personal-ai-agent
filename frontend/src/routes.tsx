import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/layout/app-shell'
import { ProtectedRoute } from '@/components/layout/protected-route'
import { LoginPage } from '@/pages/login'
import { DashboardPage } from '@/pages/dashboard'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppShell />
      </ProtectedRoute>
    ),
    children: [{ index: true, element: <DashboardPage /> }],
  },
])
