import { createFileRoute, redirect } from "@tanstack/react-router"

import { Appearance } from "@/components/Common/Appearance"
import { Footer } from "@/components/Common/Footer"
import { Logo } from "@/components/Common/Logo"
import { ProfileIntakeChat } from "@/components/CompanyProfile/ProfileIntakeChat"
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/onboarding")({
  component: Onboarding,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "Company Profile - FastAPI Template",
      },
    ],
  }),
})

function Onboarding() {
  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex items-center justify-between border-b px-6 py-4">
        <Logo variant="full" className="h-6" asLink={false} />
        <Appearance />
      </header>

      <main className="flex-1 px-6 py-10">
        <div className="mx-auto max-w-3xl">
          <div className="mb-8 text-center">
            <h1 className="text-2xl font-bold">Tell us about your company</h1>
            <p className="text-muted-foreground mt-2 text-sm">
              This profile is how we'll evaluate whether a bid fits your
              company. Chat with Aria below — the more precise your answers, the
              better the risk flags later on.
            </p>
          </div>

          <ProfileIntakeChat />
        </div>
      </main>

      <Footer />
    </div>
  )
}
