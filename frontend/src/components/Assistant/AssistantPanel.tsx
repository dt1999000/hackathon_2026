import { useMutation } from "@tanstack/react-query"
import { PanelRightClose, Send } from "lucide-react"
import { type FormEvent, useState } from "react"

import { type ChatMessage, ChatService } from "@/client"
import { Button } from "@/components/ui/button"
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

type Provider = "claude" | "local"

function ProviderSelect({
  value,
  onChange,
}: {
  value: Provider
  onChange: (value: Provider) => void
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as Provider)}>
      <SelectTrigger className="h-8 w-32 text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="claude">Claude</SelectItem>
        <SelectItem value="local">Local (Ollama)</SelectItem>
      </SelectContent>
    </Select>
  )
}

export function AssistantPanel({ onClose }: { onClose: () => void }) {
  const [provider, setProvider] = useState<Provider>("claude")
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const { showErrorToast } = useCustomToast()

  const mutation = useMutation({
    mutationFn: (nextMessages: ChatMessage[]) =>
      ChatService.sendMessage({
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

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!input.trim() || mutation.isPending) return

    const nextMessages = [...messages, { role: "user", content: input }]
    setMessages(nextMessages)
    setInput("")
    mutation.mutate(nextMessages)
  }

  return (
    <aside className="hidden h-svh w-96 shrink-0 flex-col border-l bg-background md:flex">
      <div className="flex h-16 shrink-0 items-center justify-between gap-2 border-b px-4">
        <span className="font-medium">Aria</span>
        <div className="flex items-center gap-2">
          <ProviderSelect value={provider} onChange={setProvider} />
          <Button
            variant="ghost"
            size="icon"
            className="size-7 text-muted-foreground"
            onClick={onClose}
          >
            <PanelRightClose className="size-4" />
            <span className="sr-only">Close assistant</span>
          </Button>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="text-muted-foreground text-sm">
            Ask Aria to write, summarize, translate, classify, or just chat.
          </p>
        )}
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
        {mutation.isPending && (
          <div className="self-start rounded-lg bg-muted px-3 py-2 text-muted-foreground text-sm">
            Thinking...
          </div>
        )}
      </div>

      <form onSubmit={onSubmit} className="flex shrink-0 gap-2 border-t p-3">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          disabled={mutation.isPending}
        />
        <LoadingButton
          type="submit"
          loading={mutation.isPending}
          disabled={!input.trim()}
        >
          <Send />
        </LoadingButton>
      </form>
    </aside>
  )
}
