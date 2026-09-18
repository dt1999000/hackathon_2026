import { useMutation, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router"
import { Send } from "lucide-react"
import { type FormEvent, useState } from "react"

import { type ChatMessage, CompanyProfileService } from "@/client"
import { Appearance } from "@/components/Common/Appearance"
import { Footer } from "@/components/Common/Footer"
import { Logo } from "@/components/Common/Logo"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { isLoggedIn } from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

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

// Shown locally so the chat doesn't open on a blank screen — not sent to
// the backend, since /company-profile/chat/message needs at least one
// real turn (the LLM APIs reject a call with no user message).
const GREETING =
  "Hi, I'm Aria! Let's set up your company profile together — tell me " +
  "about your company: its name, where it's based, and what kind of " +
  "work you do. We can cover the rest as we go, and whenever you feel " +
  'we\'ve covered enough, hit "Finish & save profile".'

function Onboarding() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<ChatMessage[]>([])

  const messageMutation = useMutation({
    mutationFn: (nextMessages: ChatMessage[]) =>
      CompanyProfileService.profileSendProfileChatMessage({
        body: { messages: nextMessages },
      }),
    onSuccess: (response) => {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: response.data.content },
      ])
    },
    onError: handleError.bind(showErrorToast),
  })

  const finalizeMutation = useMutation({
    mutationFn: () =>
      CompanyProfileService.profileFinalizeCompanyProfileChat({
        body: { messages },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries()
      navigate({ to: "/" })
    },
    onError: handleError.bind(showErrorToast),
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (
      !input.trim() ||
      messageMutation.isPending ||
      finalizeMutation.isPending
    )
      return

    const nextMessages = [...messages, { role: "user", content: input }]
    setMessages(nextMessages)
    setInput("")
    messageMutation.mutate(nextMessages)
  }

  const busy = messageMutation.isPending || finalizeMutation.isPending

  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex items-center justify-between border-b px-6 py-4">
        <Logo variant="full" className="h-6" asLink={false} />
        <Appearance />
      </header>

      <main className="flex flex-1 justify-center px-6 py-10">
        <div className="flex w-full max-w-2xl flex-col gap-6">
          <div className="text-center">
            <h1 className="text-2xl font-bold">Tell us about your company</h1>
            <p className="text-muted-foreground mt-2 text-sm">
              Chat with Aria instead of filling out a form — the more you share,
              the better the risk flags later on.
            </p>
          </div>

          <div className="flex min-h-96 flex-1 flex-col gap-3 overflow-y-auto rounded-lg border bg-background p-4">
            <div className="self-start rounded-lg bg-muted px-3 py-2 max-w-[90%] whitespace-pre-wrap text-sm">
              {GREETING}
            </div>
            {messages.map((msg, i) => (
              <div
                key={i}
                className={
                  msg.role === "user"
                    ? "self-end rounded-lg bg-primary px-3 py-2 text-primary-foreground max-w-[90%] whitespace-pre-wrap text-sm"
                    : "self-start rounded-lg bg-muted px-3 py-2 max-w-[90%] whitespace-pre-wrap text-sm"
                }
              >
                {msg.content}
              </div>
            ))}
            {messageMutation.isPending && (
              <div className="self-start rounded-lg bg-muted px-3 py-2 text-muted-foreground text-sm">
                Thinking...
              </div>
            )}
          </div>

          <form onSubmit={onSubmit} className="flex gap-2">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type your answer..."
              disabled={busy}
            />
            <LoadingButton
              type="submit"
              loading={messageMutation.isPending}
              disabled={!input.trim() || busy}
            >
              <Send />
            </LoadingButton>
          </form>

          <LoadingButton
            variant="outline"
            className="w-full"
            loading={finalizeMutation.isPending}
            disabled={messages.length === 0 || busy}
            onClick={() => finalizeMutation.mutate()}
          >
            Finish & save profile
          </LoadingButton>
        </div>
      </main>

      <Footer />
    </div>
  )
}
