import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Plus, Search } from "lucide-react"
import { useEffect, useState } from "react"

import { CompaniesService, WatchlistService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/companies/")({
  component: CompaniesPage,
  head: () => ({
    meta: [{ title: "Companies - FastAPI Template" }],
  }),
})

function useDebouncedValue(value: string, delayMs: number) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

function LoadingButtonSlot({
  isWatchlisted,
  loading,
  onAdd,
}: {
  isWatchlisted: boolean
  loading: boolean
  onAdd: () => void
}) {
  if (isWatchlisted) {
    return (
      <Badge variant="outline" className="text-green-600 dark:text-green-400">
        On watchlist
      </Badge>
    )
  }
  return (
    <Button size="sm" variant="outline" disabled={loading} onClick={onAdd}>
      <Plus className="h-4 w-4" />
      {loading ? "Adding..." : "Add to watchlist"}
    </Button>
  )
}

function CompaniesPage() {
  const [query, setQuery] = useState("")
  const debouncedQuery = useDebouncedValue(query, 350)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const { data: results, isFetching } = useQuery({
    queryKey: ["companies-search", debouncedQuery],
    queryFn: async () =>
      (await CompaniesService.search({ query: { q: debouncedQuery } })).data,
    enabled: debouncedQuery.trim().length > 0,
  })

  const { data: watchlist } = useQuery({
    queryKey: ["watchlist"],
    queryFn: async () => (await WatchlistService.listWatchlist()).data,
  })
  const watchlistedCiks = new Set(watchlist?.data.map((c) => c.cik) ?? [])

  const addMutation = useMutation({
    mutationFn: (cik: string) =>
      WatchlistService.addToWatchlist({ path: { cik } }),
    onSuccess: (_, cik) => {
      showSuccessToast("Added to watchlist")
      queryClient.invalidateQueries({ queryKey: ["watchlist"] })
      queryClient.invalidateQueries({ queryKey: ["companies-timeline", cik] })
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Companies</h1>
        <p className="text-muted-foreground">
          Search SEC filers and track the ones you care about
        </p>
      </div>

      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search by company name or ticker..."
          className="pl-9"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {debouncedQuery.trim().length === 0 && (
        <p className="text-muted-foreground text-sm">
          Search SEC's full company directory — not just companies already
          tracked.
        </p>
      )}

      {isFetching && (
        <p className="text-muted-foreground text-sm">Searching...</p>
      )}

      <div className="flex flex-col gap-2">
        {results?.map((company) => {
          const isWatchlisted = watchlistedCiks.has(company.cik)
          return (
            <Card
              key={company.cik}
              className="flex-row items-center justify-between px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <span className="font-medium">{company.name}</span>
                <Badge variant="secondary">{company.ticker}</Badge>
                <span className="text-muted-foreground text-xs">
                  CIK {company.cik}
                </span>
              </div>
              <LoadingButtonSlot
                isWatchlisted={isWatchlisted}
                loading={
                  addMutation.isPending && addMutation.variables === company.cik
                }
                onAdd={() => addMutation.mutate(company.cik)}
              />
            </Card>
          )
        })}
      </div>
    </div>
  )
}
