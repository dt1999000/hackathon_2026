import { useMutation } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Send } from "lucide-react"
import { type FormEvent, useState } from "react"

import { type ChatMessage, ChatService, type ResearchResponse } from "@/client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

type Provider = "claude" | "local"

export const Route = createFileRoute("/_layout/chat")({
  component: Chat,
  head: () => ({
    meta: [
      {
        title: "Chat - FastAPI Template",
      },
    ],
  }),
})

function ProviderSelect({
  value,
  onChange,
}: {
  value: Provider
  onChange: (value: Provider) => void
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as Provider)}>
      <SelectTrigger className="w-40">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="claude">Claude</SelectItem>
        <SelectItem value="local">Local (Ollama)</SelectItem>
      </SelectContent>
    </Select>
  )
}

function AriaChat() {
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
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Aria — multi-task assistant</CardTitle>
        <ProviderSelect value={provider} onChange={setProvider} />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-3 min-h-40">
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
                  ? "self-end rounded-lg bg-primary px-3 py-2 text-primary-foreground max-w-[80%] whitespace-pre-wrap"
                  : "self-start rounded-lg bg-muted px-3 py-2 max-w-[80%] whitespace-pre-wrap"
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
        <form onSubmit={onSubmit} className="flex gap-2">
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
      </CardContent>
    </Card>
  )
}

function ResearchAgent() {
  const [provider, setProvider] = useState<Provider>("claude")
  const [query, setQuery] = useState("")
  const [result, setResult] = useState<ResearchResponse | null>(null)
  const { showErrorToast } = useCustomToast()

  const mutation = useMutation({
    mutationFn: (q: string) =>
      ChatService.research({ body: { query: q, provider } }),
    onSuccess: (response) => {
      setResult(response.data)
    },
    onError: handleError.bind(showErrorToast),
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!query.trim() || mutation.isPending) return
    setResult(null)
    mutation.mutate(query)
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Research agent</CardTitle>
        <ProviderSelect value={provider} onChange={setProvider} />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-muted-foreground text-sm">
          Answers a research question using web search, Wikipedia, and a
          save-to-file tool. Small/local models may not reliably support this
          agent's tool-calling — prefer Claude here.
        </p>
        <form onSubmit={onSubmit} className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="What do you want to research?"
            disabled={mutation.isPending}
          />
          <LoadingButton
            type="submit"
            loading={mutation.isPending}
            disabled={!query.trim()}
          >
            Research
          </LoadingButton>
        </form>
        {result && (
          <div className="flex flex-col gap-3 rounded-lg border p-4">
            <div>
              <h4 className="font-semibold">{result.topic}</h4>
              <p className="whitespace-pre-wrap text-sm">{result.summary}</p>
            </div>
            {result.sources.length > 0 && (
              <div>
                <h5 className="text-sm font-medium">Sources</h5>
                <ul className="list-inside list-disc text-sm text-muted-foreground">
                  {result.sources.map((source) => (
                    <li key={source}>{source}</li>
                  ))}
                </ul>
              </div>
            )}
            {result.tools_used.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Tools used: {result.tools_used.join(", ")}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function Chat() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">Chat</h1>
      <Tabs defaultValue="chat">
        <TabsList>
          <TabsTrigger value="chat">Chat</TabsTrigger>
          <TabsTrigger value="research">Research</TabsTrigger>
        </TabsList>
        <TabsContent value="chat">
          <AriaChat />
        </TabsContent>
        <TabsContent value="research">
          <ResearchAgent />
        </TabsContent>
      </Tabs>
    </div>
  )
}
