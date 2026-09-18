const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8001"

export type PlaceType = "cafe" | "library" | "park"

export type Intent = {
  location: string
  place_type: PlaceType | "mixed"
  activity: string | null
  date: string | null
  time: string | null
  radius: number
  preferences: string[]
  include_park_if_dry: boolean
}

export type Weather = {
  temperature: number
  precipitation_probability: number | null
  description: string
  weather_code: number | null
}

export type PlaceRecommendation = {
  name: string
  address: string | null
  distance_meters: number | null
  latitude: number
  longitude: number
  reason: string
  place_type: PlaceType
}

export type ChatResponse = {
  answer: string
  intent: Intent
  weather: Weather | null
  places: PlaceRecommendation[]
  tools_used: string[]
}

export const SUGGESTIONS = [
  {
    label: "Find a study place",
    message:
      "Chiều nay mình muốn tìm một nơi yên tĩnh gần Hamburg Hbf để học. Nếu trời không mưa thì gợi ý thêm một công viên gần đó.",
  },
  {
    label: "Find a café",
    message: "Find a café near Schanze to meet a friend.",
  },
  {
    label: "Plan a walk",
    message: "Plan a walk — park near Planten un Blomen.",
  },
] as const

export class HanseGuideRequestError extends Error {
  status: number | null

  constructor(message: string, status: number | null = null) {
    super(message)
    this.name = "HanseGuideRequestError"
    this.status = status
  }
}

const TOOL_LABELS: Record<string, string> = {
  geocode_location: "Geocoding",
  get_weather: "Weather",
  search_nearby_places: "Places",
  calculate_route: "Routing",
}

export function formatToolsUsed(tools: string[]): string {
  if (tools.length === 0) {
    return "Tools used: none"
  }
  const labels = tools.map((tool) => TOOL_LABELS[tool] ?? tool)
  return `Tools used: ${labels.join(", ")}`
}

function readErrorDetail(payload: unknown): string | null {
  if (!payload || typeof payload !== "object" || !("detail" in payload)) {
    return null
  }
  const detail = (payload as { detail: unknown }).detail
  if (typeof detail === "string") {
    return detail
  }
  if (Array.isArray(detail) && detail[0] && typeof detail[0] === "object") {
    const first = detail[0] as { msg?: string }
    if (first.msg) {
      return first.msg
    }
  }
  return null
}

export async function sendHanseGuideChat(
  message: string,
): Promise<ChatResponse> {
  let response: Response
  try {
    response = await fetch(`${API_URL}/api/v1/hanseguide/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    })
  } catch {
    throw new HanseGuideRequestError(
      "Cannot reach the API. Start the backend on http://localhost:8001.",
    )
  }

  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const detail =
      readErrorDetail(payload) ?? `Request failed (${response.status})`
    if (response.status === 404) {
      throw new HanseGuideRequestError(
        "That location was not found in Hamburg. Try Hamburg Hbf, Schanze, or Planten un Blomen.",
        404,
      )
    }
    if (response.status === 502) {
      throw new HanseGuideRequestError(
        "A map or weather API timed out. Places are never invented; try again in a moment.",
        502,
      )
    }
    throw new HanseGuideRequestError(detail, response.status)
  }
  return payload as ChatResponse
}
