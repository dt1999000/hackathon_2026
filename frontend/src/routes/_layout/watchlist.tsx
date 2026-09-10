import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Search, Trash2 } from "lucide-react"

import { WatchlistService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/watchlist")({
  component: WatchlistPage,
  head: () => ({
    meta: [{ title: "Watchlist - FastAPI Template" }],
  }),
})

function WatchlistPage() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const { data: watchlist, isPending } = useQuery({
    queryKey: ["watchlist"],
    queryFn: async () => (await WatchlistService.listWatchlist()).data,
  })

  const removeMutation = useMutation({
    mutationFn: (cik: string) => WatchlistService.removeFromWatchlist({ path: { cik } }),
    onSuccess: () => {
      showSuccessToast("Removed from watchlist")
      queryClient.invalidateQueries({ queryKey: ["watchlist"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Watchlist</h1>
        <p className="text-muted-foreground">Companies you're tracking</p>
      </div>

      {isPending ? (
        <p className="text-muted-foreground text-sm">Loading...</p>
      ) : !watchlist || watchlist.data.length === 0 ? (
        <div className="flex flex-col items-center justify-center text-center py-12">
          <div className="rounded-full bg-muted p-4 mb-4">
            <Search className="h-8 w-8 text-muted-foreground" />
          </div>
          <h3 className="text-lg font-semibold">Your watchlist is empty</h3>
          <p className="text-muted-foreground">
            Search for a company and add it to get started
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {watchlist.data.map((company) => (
            <Card
              key={company.cik}
              className="flex-row items-center justify-between px-4 py-3"
            >
              <Link
                to="/companies/$cik"
                params={{ cik: company.cik }}
                className="flex items-center gap-3 hover:underline"
              >
                <span className="font-medium">{company.name}</span>
                {company.ticker && <Badge variant="secondary">{company.ticker}</Badge>}
              </Link>
              <Button
                size="sm"
                variant="ghost"
                disabled={removeMutation.isPending && removeMutation.variables === company.cik}
                onClick={() => removeMutation.mutate(company.cik)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
