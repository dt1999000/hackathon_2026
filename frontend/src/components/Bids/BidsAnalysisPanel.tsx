import { useMutation } from "@tanstack/react-query"
import { ListChecks, RefreshCw, Search } from "lucide-react"

import { BidFitService, type BidMatchResult } from "@/client"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"
import { BidMatchCard } from "./BidMatchCard"

// Matches the backend default in analyze_bids/list_contracts — keep in
// sync so "Load data" shows exactly what "Analyze" will look at.
const CONTRACTS_LIMIT = 20

export function BidsAnalysisPanel() {
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const loadMutation = useMutation({
    // Read-only — contracts are already in the DB (populated directly by
    // the scrape pipeline + scripts/import_contracts.py), so "loading"
    // them here just means fetching the most recent ones to show what
    // Analyze will run against, not inserting anything.
    mutationFn: async () =>
      (await BidFitService.fitListContracts({ query: { limit: CONTRACTS_LIMIT } })).data,
    onSuccess: (data) =>
      showSuccessToast(
        `Loaded ${data?.contracts.length ?? 0} most recent contract(s) (${data?.total_in_database ?? 0} total found)`,
      ),
    onError: handleError.bind(showErrorToast),
  })

  const analyzeMutation = useMutation({
    // timeout: 0 is axios for "no timeout" — the full pipeline runs every
    // contract's retrieval + reranking + LLM verification concurrently,
    // but each one is still several LLM/embedding calls, and external API
    // latency (rate limits, "high demand" slowdowns) can vary a lot, so a
    // fixed client-side cutoff just produces a spurious timeout instead of
    // letting the pipeline finish.
    mutationFn: async () =>
      (
        await BidFitService.fitAnalyzeBids({
          query: { source: "contracts", limit: CONTRACTS_LIMIT },
          timeout: 0,
        })
      ).data,
    onError: handleError.bind(showErrorToast),
  })

  const results: BidMatchResult[] = analyzeMutation.data?.results ?? []

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Bid matches</h2>
          <p className="text-muted-foreground">
            Load the most recently scraped contracts, then analyze them
            against your company profile.
          </p>
        </div>
        <div className="flex gap-2">
          <LoadingButton
            variant="outline"
            loading={loadMutation.isPending}
            onClick={() => loadMutation.mutate()}
          >
            <RefreshCw />
            Load data
          </LoadingButton>
          <LoadingButton
            loading={analyzeMutation.isPending}
            onClick={() => analyzeMutation.mutate()}
          >
            <Search />
            Analyze
          </LoadingButton>
        </div>
      </div>

      {analyzeMutation.isPending && (
        <p className="text-sm text-muted-foreground">
          Analyzing bids against your profile — this checks every bid against
          your hardliners with an LLM, so it can take a couple of minutes.
        </p>
      )}

      {analyzeMutation.isSuccess && results.length === 0 && (
        <div className="flex flex-col items-center justify-center text-center py-12">
          <div className="rounded-full bg-muted p-4 mb-4">
            <ListChecks className="h-8 w-8 text-muted-foreground" />
          </div>
          <h3 className="text-lg font-semibold">No bids to show</h3>
          <p className="text-muted-foreground">
            Load data first, then analyze to see your best matches here.
          </p>
        </div>
      )}

      {results.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {results.map((result) => (
            <BidMatchCard key={result.bid_id} result={result} />
          ))}
        </div>
      )}
    </div>
  )
}
