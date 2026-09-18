import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react"

import type { BidMatchResult } from "@/client"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { cn } from "@/lib/utils"

const FLAG_STYLES = {
  red: {
    card: "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/30",
    badge: "border-transparent bg-red-600 text-white dark:bg-red-500",
    icon: XCircle,
    iconClass: "text-red-600 dark:text-red-500",
    label: "Ausschluss",
  },
  yellow: {
    card: "border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/30",
    badge: "border-transparent bg-amber-500 text-white dark:bg-amber-600",
    icon: AlertTriangle,
    iconClass: "text-amber-600 dark:text-amber-500",
    label: "Mit Lösung",
  },
  green: {
    card: "border-green-300 bg-green-50 dark:border-green-900 dark:bg-green-950/30",
    badge: "border-transparent bg-green-600 text-white dark:bg-green-500",
    icon: CheckCircle2,
    iconClass: "text-green-600 dark:text-green-500",
    label: "Gute Passung",
  },
} as const

function isKnownFlag(flag: string): flag is keyof typeof FLAG_STYLES {
  return flag in FLAG_STYLES
}

export function BidMatchCard({ result }: { result: BidMatchResult }) {
  const styles = isKnownFlag(result.flag)
    ? FLAG_STYLES[result.flag]
    : FLAG_STYLES.red
  const Icon = styles.icon

  const violationByHardliner = new Map(
    result.violations.map((v) => [v.hardliner, v]),
  )
  const satisfied = result.violations.filter((v) => !v.violated)
  const scorePercent = Math.round(result.similarity_score * 100)

  return (
    <Card className={cn("gap-4", styles.card)}>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="min-w-0 flex-1 text-base leading-snug text-pretty">
            {result.title || result.notice_identifier || "Unbenannte Ausschreibung"}
          </CardTitle>
          <Badge className={cn("shrink-0", styles.badge)}>
            <Icon className={cn("size-3", styles.iconClass)} />
            {styles.label}
          </Badge>
        </div>
        {result.notice_identifier && (
          <CardDescription>
            Bekanntmachung {result.notice_identifier}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <div className="flex items-center gap-2 text-muted-foreground">
          <span className="font-medium text-foreground">
            {scorePercent}% Ähnlichkeit
          </span>
          <span>
            ·{" "}
            {result.violations.length === 1
              ? "1 Härtekriterium geprüft"
              : `${result.violations.length} Härtekriterien geprüft`}
          </span>
        </div>

        {result.flag === "red" && (
          <div className="flex flex-col gap-2">
            <p className="font-medium text-red-700 dark:text-red-400">
              Warum ausgeschlossen:
            </p>
            <ul className="flex flex-col gap-1.5">
              {result.hard_blockers.map((hardliner) => (
                <li key={hardliner}>
                  <span className="font-medium">{hardliner}:</span>{" "}
                  <span className="text-muted-foreground">
                    {violationByHardliner.get(hardliner)?.reason}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {result.flag === "yellow" && (
          <div className="flex flex-col gap-2">
            <p className="font-medium text-amber-700 dark:text-amber-400">
              Kritisch, aber lösbar:
            </p>
            <ul className="flex flex-col gap-1.5">
              {result.soft_issues.map((hardliner) => {
                const violation = violationByHardliner.get(hardliner)
                return (
                  <li key={hardliner}>
                    <span className="font-medium">{hardliner}:</span>{" "}
                    <span className="text-muted-foreground">
                      {violation?.reason}
                    </span>
                    {violation?.solution && (
                      <div className="mt-0.5 pl-0.5 text-muted-foreground">
                        <span className="font-medium text-foreground">
                          Lösung:
                        </span>{" "}
                        {violation.solution}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        )}

        {(result.flag === "yellow" || result.flag === "green") &&
          satisfied.length > 0 && (
            <div className="flex flex-col gap-2">
              <p className="font-medium">
                {result.flag === "green"
                  ? "Erfüllt alle Härtekriterien:"
                  : "Weitere erfüllte Kriterien:"}
              </p>
              <ul className="flex flex-col gap-1">
                {satisfied.map((v) => (
                  <li
                    key={v.hardliner}
                    className="flex items-start gap-1.5 text-muted-foreground"
                  >
                    <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-green-600 dark:text-green-500" />
                    {v.hardliner}
                  </li>
                ))}
              </ul>
            </div>
          )}
      </CardContent>
    </Card>
  )
}
