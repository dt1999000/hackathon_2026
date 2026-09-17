import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Send, Sparkles } from "lucide-react"
import { type FormEvent, useState } from "react"

import { type ChatMessage, CompanyProfileService } from "@/client"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

type Provider = "claude" | "local" | "google"

const GREETING =
  "Hi, I'm Aria. Let's build your company profile so we can later tell " +
  "you whether a tender is worth bidding on. Start with your company " +
  "name and what you do — we can fill in the rest as we go."

function ProviderSelect({
  value,
  onChange,
  disabled,
}: {
  value: Provider
  onChange: (value: Provider) => void
  disabled: boolean
}) {
  return (
    <Select
      value={value}
      onValueChange={(v) => onChange(v as Provider)}
      disabled={disabled}
    >
      <SelectTrigger className="h-8 w-32 text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="claude">Claude</SelectItem>
        <SelectItem value="local">Local (Ollama)</SelectItem>
        <SelectItem value="google">Google (Gemini)</SelectItem>
      </SelectContent>
    </Select>
  )
}

export function ProfileIntakeChat() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const [provider, setProvider] = useState<Provider>("google")
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<ChatMessage[]>([])

  const messageMutation = useMutation({
    mutationFn: (nextMessages: ChatMessage[]) =>
      CompanyProfileService.profileSendProfileChatMessage({
        body: { messages: nextMessages, provider },
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
        body: { messages, provider },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries()
      navigate({ to: "/" })
    },
    onError: handleError.bind(showErrorToast),
  })

  const busy = messageMutation.isPending || finalizeMutation.isPending

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!input.trim() || busy) return

    const nextMessages = [...messages, { role: "user", content: input }]
    setMessages(nextMessages)
    setInput("")
    messageMutation.mutate(nextMessages)
  }

  return (
    <div className="flex h-[70vh] flex-col rounded-lg border">
      <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b px-4">
        <span className="flex items-center gap-2 font-medium">
          <Sparkles className="size-4" />
          Aria
        </span>
        <ProviderSelect
          value={provider}
          onChange={setProvider}
          disabled={busy}
        />
      </div>

      <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
        <div className="self-start max-w-[90%] rounded-lg bg-muted px-3 py-2 text-sm whitespace-pre-wrap">
          {GREETING}
        </div>
        {messages.map((msg, i) => (
          <div
            key={i}
            className={
              msg.role === "user"
                ? "self-end max-w-[90%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground whitespace-pre-wrap"
                : "self-start max-w-[90%] rounded-lg bg-muted px-3 py-2 text-sm whitespace-pre-wrap"
            }
          >
            {msg.content}
          </div>
        ))}
        {messageMutation.isPending && (
          <div className="self-start rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
            Thinking...
          </div>
        )}
      </div>

      <div className="flex shrink-0 flex-col gap-2 border-t p-3">
        <form onSubmit={onSubmit} className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message..."
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
          type="button"
          variant="secondary"
          loading={finalizeMutation.isPending}
          disabled={messages.length === 0 || busy}
          onClick={() => finalizeMutation.mutate()}
        >
          Finish & build my profile
        </LoadingButton>
      </div>
    </div>
  )
}
