import { Link } from "@tanstack/react-router"
import {
  Building2,
  Calendar,
  MapPin,
  Users,
} from "lucide-react"

import type { CompanyProfilePublic } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useCompanyProfile } from "@/hooks/useCompanyProfile"

const TEXT_FIELDS: {
  key: keyof CompanyProfilePublic
  label: string
}[] = [
  { key: "geographic_reach", label: "Geographic reach" },
  { key: "contract_size", label: "Contract size" },
  { key: "capabilities", label: "Capabilities" },
  { key: "exclusions", label: "Exclusions" },
  { key: "certifications", label: "Certifications" },
  { key: "contractor_role", label: "Contractor role" },
  { key: "capacity", label: "Capacity" },
  { key: "reference_projects", label: "Reference projects" },
  { key: "self_description", label: "In the company's own words" },
]

function splitLines(value: string | null | undefined): string[] {
  if (!value) {
    return []
  }
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
}

function formatRevenue(value: number): string {
  return new Intl.NumberFormat("de-DE", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value)
}

function ProfileDetails({ profile }: { profile: CompanyProfilePublic }) {
  const hardliners = splitLines(profile.hardliners)
  const filledFields = TEXT_FIELDS.filter((field) => {
    const value = profile[field.key]
    return typeof value === "string" && value.trim().length > 0
  })

  return (
    <>
      <CardHeader>
        <CardDescription>Used for bid matching</CardDescription>
        <CardTitle className="flex items-start gap-2 text-xl">
          <Building2 className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
          <span className="text-pretty">{profile.company_name}</span>
        </CardTitle>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
          {profile.base_location && (
            <span className="inline-flex items-center gap-1.5">
              <MapPin className="size-3.5 shrink-0" />
              {profile.base_location}
            </span>
          )}
          {profile.founded_year != null && (
            <span className="inline-flex items-center gap-1.5">
              <Calendar className="size-3.5 shrink-0" />
              Founded {profile.founded_year}
            </span>
          )}
          {profile.employee_count != null && (
            <span className="inline-flex items-center gap-1.5">
              <Users className="size-3.5 shrink-0" />
              {profile.employee_count} employees
            </span>
          )}
          {profile.annual_revenue_eur != null && (
            <span>{formatRevenue(profile.annual_revenue_eur)} annual revenue</span>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {hardliners.length > 0 && (
          <div>
            <p className="text-sm font-medium">Hardliners</p>
            <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {hardliners.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        )}
        {filledFields.length > 0 && (
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {filledFields.map((field) => (
              <div key={field.key}>
                <dt className="text-sm font-medium">{field.label}</dt>
                <dd className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">
                  {profile[field.key] as string}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </CardContent>
      <CardFooter>
        <Button asChild variant="outline" size="sm">
          <Link to="/onboarding">Update profile</Link>
        </Button>
      </CardFooter>
    </>
  )
}

export function CompanyProfileCard() {
  const { data: profile, isLoading, isError } = useCompanyProfile()

  if (isLoading) {
    return (
      <Card data-testid="company-profile-card">
        <CardHeader>
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-7 w-72" />
          <Skeleton className="h-4 w-56" />
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
        </CardContent>
      </Card>
    )
  }

  if (isError) {
    return (
      <Card data-testid="company-profile-card">
        <CardHeader>
          <CardTitle>Company profile</CardTitle>
          <CardDescription>
            Could not load the company profile used for matching.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  if (!profile) {
    return (
      <Card data-testid="company-profile-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="size-5 text-muted-foreground" />
            No company profile
          </CardTitle>
          <CardDescription>
            Bid matching needs a company profile. Set one up so Analyze can
            score tenders against your hardliners and capabilities.
          </CardDescription>
        </CardHeader>
        <CardFooter>
          <Button asChild>
            <Link to="/onboarding">Set up profile</Link>
          </Button>
        </CardFooter>
      </Card>
    )
  }

  return (
    <Card data-testid="company-profile-card">
      <ProfileDetails profile={profile} />
    </Card>
  )
}

export function CompanyProfileIndicator() {
  const { data: profile, isLoading } = useCompanyProfile()

  if (isLoading) {
    return <Skeleton className="h-5 w-44" />
  }

  if (!profile) {
    return (
      <Link
        to="/onboarding"
        className="truncate text-sm text-muted-foreground hover:text-foreground"
      >
        Set up company profile
      </Link>
    )
  }

  return (
    <div
      className="flex min-w-0 items-center gap-2 text-sm"
      data-testid="company-profile-indicator"
      title={`Matching against ${profile.company_name}`}
    >
      <Building2 className="size-4 shrink-0 text-muted-foreground" />
      <span className="truncate">
        <span className="text-muted-foreground">Profile: </span>
        <span className="font-medium">{profile.company_name}</span>
      </span>
    </div>
  )
}
