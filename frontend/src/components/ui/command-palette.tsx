import { useEffect, useState } from 'react'
import { Command } from 'cmdk'
import { useNavigate } from 'react-router-dom'
import { LayoutDashboard, LogOut, Moon, Sun } from 'lucide-react'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

const ITEM_CLASS =
  'flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground'
const DESTRUCTIVE_ITEM_CLASS = `${ITEM_CLASS} text-destructive`

export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const logout = useAuthStore((s) => s.logout)
  const { theme, toggleTheme } = useThemeStore()

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
        event.preventDefault()
        setOpen((prev) => !prev)
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])

  function run(action: () => void) {
    setOpen(false)
    action()
  }

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command palette"
      className="fixed left-1/2 top-24 z-50 w-full max-w-md -translate-x-1/2 overflow-hidden rounded-lg border border-border bg-card text-card-foreground shadow-lg"
    >
      <Command.Input
        placeholder="Type a command..."
        className="w-full border-b border-border bg-transparent px-4 py-3 text-sm outline-none placeholder:text-muted-foreground"
      />
      <Command.List className="max-h-80 overflow-y-auto p-2">
        <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
          No results found.
        </Command.Empty>
        <Command.Item onSelect={() => run(() => navigate('/'))} className={ITEM_CLASS}>
          <LayoutDashboard className="h-4 w-4" /> Go to dashboard
        </Command.Item>
        <Command.Item onSelect={() => run(toggleTheme)} className={ITEM_CLASS}>
          {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          Toggle theme
        </Command.Item>
        <Command.Item onSelect={() => run(logout)} className={DESTRUCTIVE_ITEM_CLASS}>
          <LogOut className="h-4 w-4" /> Log out
        </Command.Item>
      </Command.List>
    </Command.Dialog>
  )
}
