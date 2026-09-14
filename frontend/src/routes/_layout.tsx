import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"
import { PanelRightOpen } from "lucide-react"
import { useEffect, useState } from "react"

import { AssistantPanel } from "@/components/Assistant/AssistantPanel"
import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import { Button } from "@/components/ui/button"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { isLoggedIn } from "@/hooks/useAuth"

const ASSISTANT_PANEL_STORAGE_KEY = "assistant-panel-open"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

function Layout() {
  const [assistantOpen, setAssistantOpen] = useState(
    () => localStorage.getItem(ASSISTANT_PANEL_STORAGE_KEY) !== "false",
  )

  useEffect(() => {
    localStorage.setItem(ASSISTANT_PANEL_STORAGE_KEY, String(assistantOpen))
  }, [assistantOpen])

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <div className="flex min-h-svh flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-2 border-b bg-background px-4">
              <SidebarTrigger className="-ml-1 text-muted-foreground" />
              <div className="flex-1" />
              {!assistantOpen && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="hidden size-7 text-muted-foreground md:inline-flex"
                  onClick={() => setAssistantOpen(true)}
                >
                  <PanelRightOpen className="size-4" />
                  <span className="sr-only">Open assistant</span>
                </Button>
              )}
            </header>
            <main className="flex-1 p-6 md:p-8">
              <div className="mx-auto max-w-7xl">
                <Outlet />
              </div>
            </main>
            <Footer />
          </div>
          {assistantOpen && (
            <AssistantPanel onClose={() => setAssistantOpen(false)} />
          )}
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
