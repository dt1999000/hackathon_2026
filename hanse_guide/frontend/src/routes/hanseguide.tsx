import { createFileRoute } from "@tanstack/react-router"

import { HanseGuidePage } from "@/components/HanseGuide/HanseGuidePage"

export const Route = createFileRoute("/hanseguide")({
  component: HanseGuidePage,
  head: () => ({
    meta: [
      {
        title: "HanseGuide",
      },
    ],
  }),
})
