import { BookOpen, CloudSun, Coffee, MapPin, Send, Trees } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Appearance } from "@/components/Common/Appearance"
import { HanseGuideMap } from "@/components/HanseGuide/HanseGuideMap"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import {
  type ChatResponse,
  formatToolsUsed,
  SUGGESTIONS,
  sendHanseGuideChat,
} from "@/lib/hanseguide"
import { cn } from "@/lib/utils"

type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
}

const PLACE_ICONS = {
  cafe: Coffee,
  library: BookOpen,
  park: Trees,
}

export function HanseGuidePage() {
  const { showErrorToast } = useCustomToast()
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Ask me for a café, library, or park in Hamburg. I use weather and OpenStreetMap data and will not invent places.",
    },
  ])
  const [result, setResult] = useState<ChatResponse | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const transcriptLength = messages.length

  useEffect(() => {
    if (transcriptLength === 0 && !loading) {
      return
    }
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [transcriptLength, loading])

  const sendMessage = async (text: string) => {
    const message = text.trim()
    if (!message || loading) {
      return
    }
    setInput("")
    setLoading(true)
    setRequestError(null)
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", content: message },
    ])
    try {
      const response = await sendHanseGuideChat(message)
      setResult(response)
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: response.answer,
        },
      ])
    } catch (error) {
      const description =
        error instanceof Error ? error.message : "Could not reach HanseGuide."
      setRequestError(description)
      showErrorToast(description)
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `I could not complete that request. ${description}`,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-background min-h-svh">
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4">
          <div>
            <p className="text-muted-foreground text-xs tracking-wide uppercase">
              Hamburg local assistant
            </p>
            <h1 className="text-lg font-semibold">HanseGuide</h1>
          </div>
          <Appearance />
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-6 px-4 py-6 lg:grid-cols-[1.15fr_0.85fr]">
        <section className="flex min-h-[70vh] flex-col gap-4">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
              What would you like to do in Hamburg?
            </h2>
            <p className="text-muted-foreground mt-1 text-sm">
              Describe a café, a quiet study spot, or a walk. I will pick APIs
              and recommend real places.
            </p>
          </div>

          {requestError ? (
            <Alert variant="destructive">
              <AlertTitle>Request failed</AlertTitle>
              <AlertDescription>{requestError}</AlertDescription>
            </Alert>
          ) : null}

          <div className="flex flex-wrap gap-2">
            {SUGGESTIONS.map((suggestion) => (
              <Button
                key={suggestion.label}
                type="button"
                variant="outline"
                size="sm"
                disabled={loading}
                onClick={() => void sendMessage(suggestion.message)}
              >
                {suggestion.label}
              </Button>
            ))}
          </div>

          <Card className="flex min-h-0 flex-1 flex-col py-0">
            <CardContent className="flex min-h-0 flex-1 flex-col p-0">
              <div
                ref={listRef}
                className="flex flex-1 flex-col gap-3 overflow-y-auto p-4"
              >
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={cn(
                      "max-w-[85%] rounded-xl px-3 py-2 text-sm leading-relaxed",
                      message.role === "user"
                        ? "bg-primary text-primary-foreground ml-auto"
                        : "bg-muted mr-auto",
                    )}
                  >
                    {message.content}
                  </div>
                ))}
                {loading ? (
                  <div className="bg-muted text-muted-foreground mr-auto rounded-xl px-3 py-2 text-sm">
                    Looking up weather and places…
                  </div>
                ) : null}
              </div>
              <form
                className="flex gap-2 border-t p-3"
                onSubmit={(event) => {
                  event.preventDefault()
                  void sendMessage(input)
                }}
              >
                <Input
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  placeholder="Ask for a café, library, or park…"
                  disabled={loading}
                  aria-label="Message"
                />
                <LoadingButton
                  type="submit"
                  loading={loading}
                  disabled={!input.trim()}
                >
                  <Send className="size-4" />
                  Send
                </LoadingButton>
              </form>
            </CardContent>
          </Card>
        </section>

        <aside className="flex flex-col gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CloudSun className="size-4" />
                Weather
              </CardTitle>
              <CardDescription>
                {result?.intent.location ??
                  "Ask a question to load the forecast."}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {result?.weather ? (
                <div className="space-y-1">
                  <p className="text-3xl font-semibold">
                    {Math.round(result.weather.temperature)}°C
                  </p>
                  <p>{result.weather.description}</p>
                  <p className="text-muted-foreground text-sm">
                    Rain chance:{" "}
                    {result.weather.precipitation_probability == null
                      ? "unknown"
                      : `${result.weather.precipitation_probability}%`}
                  </p>
                </div>
              ) : result ? (
                <p className="text-muted-foreground text-sm">
                  Weather data was unavailable for this request.
                </p>
              ) : (
                <p className="text-muted-foreground text-sm">
                  Weather appears here after the first reply.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <MapPin className="size-4" />
                Map
              </CardTitle>
              <CardDescription>
                OpenStreetMap markers for the recommended places.
                {result && result.places.length === 0
                  ? " No places to plot — showing Hamburg."
                  : ""}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <HanseGuideMap places={result?.places ?? []} />
            </CardContent>
          </Card>

          <Card className="flex-1">
            <CardHeader>
              <CardTitle>Places</CardTitle>
              <CardDescription>
                Names come from OpenStreetMap, not from the model.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {result?.places.length ? (
                result.places.map((place) => {
                  const Icon = PLACE_ICONS[place.place_type]
                  return (
                    <div
                      key={`${place.name}-${place.latitude}-${place.longitude}`}
                      className="rounded-lg border p-3"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2 font-medium">
                          <Icon className="size-4 shrink-0" />
                          {place.name}
                        </div>
                        <Badge variant="secondary">{place.place_type}</Badge>
                      </div>
                      <p className="text-muted-foreground mt-1 flex items-center gap-1 text-sm">
                        <MapPin className="size-3" />
                        {place.address ?? "Address unavailable"}
                        {place.distance_meters != null
                          ? ` · ${place.distance_meters} m`
                          : ""}
                      </p>
                      <p className="mt-2 text-sm">{place.reason}</p>
                    </div>
                  )
                })
              ) : result ? (
                <p className="text-muted-foreground text-sm">
                  No matching OpenStreetMap places were found. Try another area
                  or a café, library, or park.
                </p>
              ) : (
                <p className="text-muted-foreground text-sm">
                  Recommended cafés, libraries, and parks will show up here.
                </p>
              )}
            </CardContent>
          </Card>

          <p className="text-muted-foreground px-1 text-xs">
            {formatToolsUsed(result?.tools_used ?? [])}
          </p>
        </aside>
      </main>
    </div>
  )
}
