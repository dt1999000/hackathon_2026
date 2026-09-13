import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Sparkles,
} from "lucide-react"

import {
  CompaniesService,
  type FilingTimelineEntry,
  IngestionService,
  type MetricChange,
  type NarrativeChangePublic,
  type RiskFlag,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/companies/$cik")({
  component: CompanyDetailPage,
})

function formatUsd(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(2)}M`
  return `$${value.toFixed(0)}`
}

function formatMetricValue(metric: MetricChange): string {
  if (metric.current_value === null) return "—"
  if (metric.unit === "ratio") return metric.current_value.toFixed(2)
  if (metric.unit === "USD/day") return `${formatUsd(metric.current_value)}/day`
  return formatUsd(metric.current_value)
}

function MetricPill({ metric }: { metric: MetricChange }) {
  if (metric.current_value === null || metric.change_pct === null) return null
  const isUp = metric.change_pct > 0
  const isFlat = Math.abs(metric.change_pct) < 0.05
  const Icon = isFlat ? ArrowRight : isUp ? ArrowUp : ArrowDown
  return (
    <span className="inline-flex items-center gap-1 rounded-md border bg-muted/50 px-2 py-1 text-xs">
      <span className="text-muted-foreground">
        {metric.metric.replace(/_/g, " ")}
      </span>
      <span className="font-medium">{formatMetricValue(metric)}</span>
      <span
        className={
          isFlat
            ? "text-muted-foreground flex items-center"
            : isUp
              ? "text-amber-600 dark:text-amber-400 flex items-center"
              : "text-sky-600 dark:text-sky-400 flex items-center"
        }
      >
        <Icon className="h-3 w-3" />
        {Math.abs(metric.change_pct).toFixed(1)}%
      </span>
    </span>
  )
}

function RiskFlagRow({ flag }: { flag: RiskFlag }) {
  return (
    <div className="flex items-start gap-2 text-sm">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
      <span>{flag.message}</span>
    </div>
  )
}

function NarrativeChangeRow({ change }: { change: NarrativeChangePublic }) {
  const variant =
    change.change_type === "new"
      ? "default"
      : change.change_type === "removed"
        ? "destructive"
        : "secondary"
  return (
    <div className="flex items-start gap-2 text-sm">
      <Badge variant={variant} className="mt-0.5 shrink-0 capitalize">
        {change.change_type}
      </Badge>
      <span className="text-muted-foreground">{change.summary}</span>
    </div>
  )
}

function AnalyzeButton({
  filingId,
  sectionType,
  cik,
}: {
  filingId: string
  sectionType: "risk_factors" | "legal_proceedings"
  cik: string
}) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const mutation = useMutation({
    mutationFn: () =>
      IngestionService.computeNarrativeDiff({
        path: { filing_id: filingId },
        query: { section_type: sectionType },
      }),
    onSuccess: (result) => {
      showSuccessToast(`Found ${result.data?.count ?? 0} narrative change(s)`)
      queryClient.invalidateQueries({ queryKey: ["companies-timeline", cik] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const label =
    sectionType === "risk_factors" ? "Risk Factors" : "Legal Proceedings"

  return (
    <LoadingButton
      size="sm"
      variant="outline"
      loading={mutation.isPending}
      onClick={() => mutation.mutate()}
      title="Runs a local LLM over both filings — can take several minutes"
    >
      <Sparkles className="h-3.5 w-3.5" />
      {mutation.isPending
        ? "Analyzing (this can take several minutes)..."
        : `Analyze ${label}`}
    </LoadingButton>
  )
}

function TimelineNode({
  filing,
  cik,
  isLast,
}: {
  filing: FilingTimelineEntry
  cik: string
  isLast: boolean
}) {
  const riskChanges = filing.narrative_changes.filter(
    (c) => c.section_type === "risk_factors",
  )
  const legalChanges = filing.narrative_changes.filter(
    (c) => c.section_type === "legal_proceedings",
  )
  const hasComparison = filing.signals !== null

  return (
    <div className="relative flex gap-4 pb-8">
      {!isLast && (
        <div className="absolute left-[7px] top-4 bottom-0 w-px bg-border" />
      )}
      <div className="relative z-10 mt-1.5 h-4 w-4 shrink-0 rounded-full border-2 border-primary bg-background" />
      <Card className="flex-1 gap-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{filing.form_type}</Badge>
          <span className="font-medium">{filing.filing_date}</span>
          {filing.period_of_report && (
            <span className="text-muted-foreground text-xs">
              period ending {filing.period_of_report}
            </span>
          )}
        </div>

        {!hasComparison && (
          <p className="text-muted-foreground text-xs">
            First tracked filing of this type — nothing to compare against yet.
          </p>
        )}

        {filing.structured_risk_flags &&
          filing.structured_risk_flags.flags.length > 0 && (
            <div className="flex flex-col gap-1.5 rounded-md border border-amber-600/30 bg-amber-600/5 p-3 dark:border-amber-400/30 dark:bg-amber-400/5">
              {filing.structured_risk_flags.flags.map((flag) => (
                <RiskFlagRow key={flag.flag_type} flag={flag} />
              ))}
            </div>
          )}

        {filing.signals?.debt_and_liquidity.some(
          (m) => m.current_value !== null,
        ) && (
          <div className="flex flex-wrap gap-2">
            {filing.signals.debt_and_liquidity.map((metric) => (
              <MetricPill key={metric.metric} metric={metric} />
            ))}
            {filing.signals.capex.current_value !== null && (
              <MetricPill metric={filing.signals.capex} />
            )}
          </div>
        )}

        {hasComparison && (
          <div className="flex flex-col gap-3 border-t pt-3">
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground">
                  Risk Factors
                </span>
                <AnalyzeButton
                  filingId={filing.filing_id}
                  sectionType="risk_factors"
                  cik={cik}
                />
              </div>
              {riskChanges.length > 0 ? (
                <div className="flex flex-col gap-1">
                  {riskChanges.map((c, i) => (
                    <NarrativeChangeRow key={i} change={c} />
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground text-xs">
                  Not yet analyzed.
                </p>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground">
                  Legal Proceedings
                </span>
                <AnalyzeButton
                  filingId={filing.filing_id}
                  sectionType="legal_proceedings"
                  cik={cik}
                />
              </div>
              {legalChanges.length > 0 ? (
                <div className="flex flex-col gap-1">
                  {legalChanges.map((c, i) => (
                    <NarrativeChangeRow key={i} change={c} />
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground text-xs">
                  Not yet analyzed.
                </p>
              )}
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}

function CompanyDetailPage() {
  const { cik } = Route.useParams()

  const { data: timeline, isPending } = useQuery({
    queryKey: ["companies-timeline", cik],
    queryFn: async () =>
      (await CompaniesService.getTimeline({ path: { cik } })).data,
  })

  if (isPending) {
    return <p className="text-muted-foreground text-sm">Loading...</p>
  }

  if (!timeline) {
    return <p className="text-muted-foreground text-sm">Company not found.</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold tracking-tight">
            {timeline.company.name}
          </h1>
          {timeline.company.ticker && (
            <Badge variant="secondary">{timeline.company.ticker}</Badge>
          )}
        </div>
        <p className="text-muted-foreground">
          CIK {timeline.company.cik} · {timeline.filings.length} filings tracked
        </p>
      </div>

      {timeline.filings.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          No filings ingested yet.
        </p>
      ) : (
        <div className="flex flex-col">
          {timeline.filings.map((filing, i) => (
            <TimelineNode
              key={filing.filing_id}
              filing={filing}
              cik={cik}
              isLast={i === timeline.filings.length - 1}
            />
          ))}
        </div>
      )}
    </div>
  )
}
