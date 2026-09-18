# HanseGuide

> **HanseGuide is an AI-powered local assistant for Hamburg. Users can describe what they want to do in natural language, such as finding a quiet place to study or planning an outdoor activity. The agent automatically selects and calls geocoding, places and weather APIs, combines the results and produces a personalized recommendation. The backend is implemented with FastAPI, while the frontend provides a conversational interface and location-based result cards.**

MVP: cafés, libraries, and parks only. No login, database, booking, or public transit. Place names always come from OpenStreetMap — the model never invents them.

Copy this folder independently of the root FastAPI template. Backend port **8001**, frontend port **5174**.

## How to run

Copy `hanse_guide/.env.example` to `hanse_guide/.env` if needed. Leave `DATABASE_URL` unset.

Ollama is optional. If it is not running, a keyword parser still extracts intent.

### Backend

```bash
cd hanse_guide/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
fastapi dev --port 8001
```

- App: http://localhost:8001
- Docs: http://localhost:8001/docs
- Health: http://localhost:8001/api/v1/hanseguide/health

### Frontend

```bash
cd hanse_guide/frontend
npm install
npm run dev
```

Open **http://localhost:5174/hanseguide** (no sign-in).

`hanse_guide/frontend/.env` should contain:

```bash
VITE_API_URL=http://localhost:8001
```

Optional Ollama in `hanse_guide/.env`:

```bash
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

## Demo questions (16/9)

Use the chips on the page, or paste these into chat:

1. **Study (quiet + park if dry)**  
   `Chiều nay mình muốn tìm một nơi yên tĩnh gần Hamburg Hbf để học. Nếu trời không mưa thì gợi ý thêm một công viên gần đó.`

2. **Café**  
   `Find a café near Schanze to meet a friend.`

3. **Walk**  
   `Plan a walk — park near Planten un Blomen.`

Expected result each time: chatbot answer, weather card, 3–5 real places, map markers, and `Tools used: Geocoding, Weather, Places`.

### 60-second script

1. Open http://localhost:5174/hanseguide.
2. Click **Find a study place** — libraries near Hamburg Hbf; a park only if rain chance is low.
3. Click **Find a café** — cafés around Sternschanze on the map.
4. Click **Plan a walk** — parks near Planten un Blomen.
5. Point at **Tools used** so it is clear the agent called real APIs.

## Error states

| Situation | What you should see |
| --- | --- |
| Backend not running | Red alert + chat: cannot reach the API on port 8001 |
| Unknown place (`near zzzqwerty123`) | 404: location not found in Hamburg |
| Nominatim down | 502: location lookup failed |
| Overpass busy / 504 | Chat retries other OSM servers. If all fail: weather still shown, empty places, no invented names |
| Successful chat but OSM empty | Places panel: no matching OpenStreetMap places |
| Weather API skipped | Weather panel: data unavailable for this request |
| Ollama stopped | App still works via keyword fallback; health may be `degraded` |

Try a failed location without stopping the demo:

```text
Find a café near zzzqwerty123
```

A name that Nominatim can resolve inside Hamburg (for example Atlantis) will not 404. Place search retries Overpass mirrors; if every server times out, chat still answers with weather and an empty place list instead of dumping a 504.

## Pitch (16/9)

HanseGuide is an AI-powered local assistant for Hamburg. Users can describe what they want to do in natural language, such as finding a quiet place to study or planning an outdoor activity. The agent automatically selects and calls geocoding, places and weather APIs, combines the results and produces a personalized recommendation. The backend is implemented with FastAPI, while the frontend provides a conversational interface and location-based result cards.
