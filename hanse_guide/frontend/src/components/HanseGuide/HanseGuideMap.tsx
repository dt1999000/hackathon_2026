import L from "leaflet"
import { useEffect } from "react"
import {
  CircleMarker,
  MapContainer,
  Popup,
  TileLayer,
  useMap,
} from "react-leaflet"

import type { PlaceRecommendation, PlaceType } from "@/lib/hanseguide"

import "leaflet/dist/leaflet.css"

const HAMBURG: L.LatLngExpression = [53.5511, 9.9937]

const MARKER_COLORS: Record<PlaceType, string> = {
  cafe: "#d97706",
  library: "#0d9488",
  park: "#16a34a",
}

function FitPlaces({ places }: { places: PlaceRecommendation[] }) {
  const map = useMap()

  useEffect(() => {
    if (places.length === 0) {
      map.setView(HAMBURG, 12)
      return
    }
    const bounds = L.latLngBounds(
      places.map((place) => [place.latitude, place.longitude]),
    )
    map.fitBounds(bounds, { padding: [28, 28], maxZoom: 16 })
  }, [map, places])

  return null
}

export function HanseGuideMap({ places }: { places: PlaceRecommendation[] }) {
  return (
    <div className="z-0 h-64 overflow-hidden rounded-lg">
      <MapContainer
        center={HAMBURG}
        zoom={12}
        scrollWheelZoom
        className="z-0 h-full w-full"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitPlaces places={places} />
        {places.map((place) => (
          <CircleMarker
            key={`${place.name}-${place.latitude}-${place.longitude}`}
            center={[place.latitude, place.longitude]}
            radius={9}
            pathOptions={{
              color: MARKER_COLORS[place.place_type],
              fillColor: MARKER_COLORS[place.place_type],
              fillOpacity: 0.9,
              weight: 2,
            }}
          >
            <Popup>
              <strong>{place.name}</strong>
              <br />
              {place.address ?? "Address unavailable"}
              {place.distance_meters != null
                ? ` · ${place.distance_meters} m`
                : ""}
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  )
}
