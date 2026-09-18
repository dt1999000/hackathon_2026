import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ListChecks, RefreshCw, Search } from "lucide-react"

import { BidFitService, type BidMatchResult, BidsService } from "@/client"
import { CompanyProfileCard } from "@/components/CompanyProfile/CompanyProfileCard"
import { LoadingButton } from "@/components/ui/loading-button"
import { useCompanyProfile } from "@/hooks/useCompanyProfile"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"
import { BidMatchCard } from "./BidMatchCard"

const RESULT_SECTIONS = [
  {
    flag: "green",
    title: "Gute Treffer",
    description: "Keine Härtekriterien verletzt — diese passen zum Profil.",
  },
  {
    flag: "yellow",
    title: "Warnungen",
    description: "Konflikte, die sich mit einer realistischen Lösung beheben lassen.",
  },
  {
    flag: "red",
    title: "Schlechte Treffer",
    description: "Ausschluss — mindestens ein K.o.-Kriterium ohne realistische Lösung.",
  },
] as const

export function BidsAnalysisPanel() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { data: profile } = useCompanyProfile()

  const { data: bids } = useQuery({
    queryKey: ["bids"],
    queryFn: async () => (await BidsService.listBids()).data ?? [],
  })

  const loadMutation = useMutation({
    mutationFn: async () => (await BidsService.loadBids()).data,
    onSuccess: (data) => {
      showSuccessToast(data?.message ?? "Bids loaded")
      queryClient.invalidateQueries({ queryKey: ["bids"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const analyzeMutation = useMutation({
    // timeout: 0 is axios for "no timeout" — the full pipeline runs every
    // seeded bid's retrieval + reranking + LLM verification concurrently,
    // but each one is still several LLM/embedding calls, and external API
    // latency (rate limits, "high demand" slowdowns) can vary a lot, so a
    // fixed client-side cutoff just produces a spurious timeout instead of
    // letting the pipeline finish.
    mutationFn: async () =>
      (await BidFitService.fitAnalyzeBids({ timeout: 0 })).data,
    onError: handleError.bind(showErrorToast),
  })

  const results: BidMatchResult[] = analyzeMutation.data?.results ?? []
  const loadedBids = bids ?? []

  const profileName = profile?.company_name
  const canAnalyze = Boolean(profile)

  return (
    <div className="flex flex-col gap-6">
      <CompanyProfileCard />
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Bid matches</h2>
          <p className="text-muted-foreground">
            Load the sample bids, then analyze them against{" "}
            {profileName ? (
              <span className="font-medium text-foreground">{profileName}</span>
            ) : (
              "your company profile"
            )}
            . Results show two good matches, two warnings, and two poor
            matches when those flags exist.
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
            disabled={!canAnalyze}
            title={
              canAnalyze
                ? undefined
                : "Set up a company profile before analyzing bids"
            }
            onClick={() => analyzeMutation.mutate()}
          >
            <Search />
            Analyze
          </LoadingButton>
        </div>
      </div>

      {analyzeMutation.isPending && (
        <p className="text-sm text-muted-foreground">
          Analyzing bids against {profileName ?? "your profile"} — this checks
          every bid against your hardliners with an LLM, so it can take a
          couple of minutes.
        </p>
      )}

      {analyzeMutation.isSuccess && results.length === 0 && (
        <div className="flex flex-col items-center justify-center text-center py-12">
          <div className="rounded-full bg-muted p-4 mb-4">
            <ListChecks className="h-8 w-8 text-muted-foreground" />
          </div>
          <h3 className="text-lg font-semibold">No bids to show</h3>
          <p className="text-muted-foreground">
            Load data first, then analyze to see good matches, warnings, and
            poor matches here.
          </p>
        </div>
      )}

      {results.length > 0 && (
        <div className="flex flex-col gap-8">
          {RESULT_SECTIONS.map((section) => {
            const group = results.filter((result) => result.flag === section.flag)
            if (group.length === 0) {
              return null
            }
            return (
              <section key={section.flag} className="flex flex-col gap-3">
                <div>
                  <h3 className="text-lg font-semibold tracking-tight">
                    {section.title}
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    {section.description}
                  </p>
                </div>
                <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
                  {group.map((result) => (
                    <BidMatchCard key={result.bid_id} result={result} />
                  ))}
                </div>
              </section>
            )
          })}
        </div>
      )}

      {results.length === 0 && !analyzeMutation.isPending && loadedBids.length > 0 && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            {loadedBids.length} bid{loadedBids.length === 1 ? "" : "s"} loaded.
            Click Analyze to score them against{" "}
            {profileName ?? "your profile"}.
          </p>
          <ul className="divide-y rounded-lg border">
            {loadedBids.map((bid) => (
              <li key={bid.id} className="px-4 py-3">
                <p className="font-medium leading-snug">
                  {bid.title || bid.source_file}
                </p>
                <p className="text-sm text-muted-foreground">
                  {[bid.notice_identifier, bid.place_of_performance]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
