import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Command, LogOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { ThemeToggle } from '@/components/layout/theme-toggle'
import { CommandPalette } from '@/components/ui/command-palette'
import { useAuthStore } from '@/stores/auth'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard' },
  { to: '/profile', label: 'Profile' },
  { to: '/research', label: 'Research' },
  { to: '/search', label: 'Search' },
  { to: '/gmail', label: 'Gmail' },
  { to: '/career', label: 'Career' },
  { to: '/applications', label: 'Applications' },
]

export function AppShell() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <CommandPalette />
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border px-4 py-3 sm:px-6">
        <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-2">
          <div className="flex items-center gap-2 whitespace-nowrap font-semibold">
            <span className="h-2 w-2 rounded-full bg-primary" />
            Personal AI Agent
          </div>
          <nav className="flex flex-wrap items-center gap-1">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  cn(
                    'rounded-md px-3 py-1.5 text-sm transition-colors hover:bg-accent hover:text-accent-foreground',
                    isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground'
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <div className="hidden items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground sm:flex">
            <Command className="h-3 w-3" /> K
          </div>
          <ThemeToggle />
          {user && (
            <>
              <span className="hidden text-sm text-muted-foreground md:inline">{user.email}</span>
              <Button variant="ghost" size="icon" aria-label="Log out" onClick={handleLogout}>
                <LogOut className="h-4 w-4" />
              </Button>
            </>
          )}
        </div>
      </header>
      <motion.main
        key={location.pathname}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.15 }}
        className="min-w-0 flex-1 p-4 sm:p-6"
      >
        <Outlet />
      </motion.main>
    </div>
  )
}
