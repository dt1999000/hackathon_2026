import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router"
import { Plus, Trash2 } from "lucide-react"
import { useFieldArray, useForm } from "react-hook-form"
import { z } from "zod"

import { type CompanyProfileCreate, CompanyProfileService } from "@/client"
import { Appearance } from "@/components/Common/Appearance"
import { Footer } from "@/components/Common/Footer"
import { Logo } from "@/components/Common/Logo"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { isLoggedIn } from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const formSchema = z.object({
  company_name: z.string().min(1, { message: "Company name is required" }),
  base_location: z.string().optional(),
  founded_year: z.string().optional(),
  employee_count: z.string().optional(),
  annual_revenue_eur: z.string().optional(),

  max_radius_km: z.string().optional(),
  served_regions: z.string().optional(),
  excluded_regions: z.string().optional(),

  min_contract_value_eur: z.string().optional(),
  max_contract_value_eur: z.string().optional(),
  partner_threshold_eur: z.string().optional(),

  capabilities: z.string().optional(),
  explicit_exclusions: z.string().optional(),
  certifications: z.string().optional(),

  contractor_role: z.string().optional(),
  max_self_perform_pct: z.string().optional(),

  guarantee_limit_total_eur: z.string().optional(),
  guarantee_currently_committed_eur: z.string().optional(),

  available_from: z.string().optional(),
  capacity_note: z.string().optional(),

  reference_projects: z.string().optional(),
  custom_hardliners: z.array(z.object({ value: z.string() })),
})

type FormData = z.infer<typeof formSchema>

export const Route = createFileRoute("/onboarding")({
  component: Onboarding,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "Company Profile - FastAPI Template",
      },
    ],
  }),
})

function toOptionalNumber(raw: string | undefined): number | undefined {
  if (!raw || raw.trim() === "") return undefined
  const parsed = Number(raw)
  return Number.isNaN(parsed) ? undefined : parsed
}

function parseLines(raw: string | undefined): string[] {
  return (raw ?? "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

function Onboarding() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      company_name: "",
      base_location: "",
      founded_year: "",
      employee_count: "",
      annual_revenue_eur: "",
      max_radius_km: "",
      served_regions: "",
      excluded_regions: "",
      min_contract_value_eur: "",
      max_contract_value_eur: "",
      partner_threshold_eur: "",
      capabilities: "",
      explicit_exclusions: "",
      certifications: "",
      contractor_role: "",
      max_self_perform_pct: "",
      guarantee_limit_total_eur: "",
      guarantee_currently_committed_eur: "",
      available_from: "",
      capacity_note: "",
      reference_projects: "",
      custom_hardliners: [{ value: "" }],
    },
  })

  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "custom_hardliners",
  })

  const mutation = useMutation({
    mutationFn: (data: CompanyProfileCreate) =>
      CompanyProfileService.profileCreateCompanyProfileMe({ body: data }),
    onSuccess: () => {
      queryClient.invalidateQueries()
      navigate({ to: "/" })
    },
    onError: handleError.bind(showErrorToast),
  })

  const onSubmit = (data: FormData) => {
    if (mutation.isPending) return

    const payload: CompanyProfileCreate = {
      company_name: data.company_name,
      base_location: data.base_location || undefined,
      founded_year: toOptionalNumber(data.founded_year),
      employee_count: toOptionalNumber(data.employee_count),
      annual_revenue_eur: toOptionalNumber(data.annual_revenue_eur),

      max_radius_km: toOptionalNumber(data.max_radius_km),
      served_regions: parseLines(data.served_regions),
      excluded_regions: parseLines(data.excluded_regions),

      min_contract_value_eur: toOptionalNumber(data.min_contract_value_eur),
      max_contract_value_eur: toOptionalNumber(data.max_contract_value_eur),
      partner_threshold_eur: toOptionalNumber(data.partner_threshold_eur),

      capabilities: parseLines(data.capabilities),
      explicit_exclusions: parseLines(data.explicit_exclusions),
      certifications: parseLines(data.certifications),

      contractor_role: data.contractor_role || undefined,
      max_self_perform_pct: toOptionalNumber(data.max_self_perform_pct),

      guarantee_limit_total_eur: toOptionalNumber(
        data.guarantee_limit_total_eur,
      ),
      guarantee_currently_committed_eur: toOptionalNumber(
        data.guarantee_currently_committed_eur,
      ),

      available_from: data.available_from || undefined,
      capacity_note: data.capacity_note || undefined,

      reference_projects: parseLines(data.reference_projects),
      custom_hardliners: data.custom_hardliners
        .map((h) => h.value.trim())
        .filter((v) => v.length > 0),
    }

    mutation.mutate(payload)
  }

  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex items-center justify-between border-b px-6 py-4">
        <Logo variant="full" className="h-6" asLink={false} />
        <Appearance />
      </header>

      <main className="flex-1 px-6 py-10">
        <div className="mx-auto max-w-3xl">
          <div className="mb-8 text-center">
            <h1 className="text-2xl font-bold">Tell us about your company</h1>
            <p className="text-muted-foreground mt-2 text-sm">
              This profile is how we'll evaluate whether a bid fits your
              company. The more precise, the better the risk flags later on.
            </p>
          </div>

          <Form {...form}>
            <form
              onSubmit={form.handleSubmit(onSubmit)}
              className="flex flex-col gap-6"
            >
              <Card>
                <CardHeader>
                  <CardTitle>Company Basics</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 sm:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="company_name"
                    render={({ field }) => (
                      <FormItem className="sm:col-span-2">
                        <FormLabel>Company name</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="Brenner & Sohn Tiefbau GmbH"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="base_location"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Base location</FormLabel>
                        <FormControl>
                          <Input placeholder="Augsburg, Bavaria" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="founded_year"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Founded year</FormLabel>
                        <FormControl>
                          <Input type="number" placeholder="1962" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="employee_count"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Employees</FormLabel>
                        <FormControl>
                          <Input type="number" placeholder="140" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="annual_revenue_eur"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Annual revenue (EUR)</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            placeholder="31000000"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Geographic Reach</CardTitle>
                  <CardDescription>
                    Where you work, and anywhere you've ruled out entirely.
                  </CardDescription>
                </CardHeader>
                <CardContent className="grid gap-4">
                  <FormField
                    control={form.control}
                    name="max_radius_km"
                    render={({ field }) => (
                      <FormItem className="sm:max-w-xs">
                        <FormLabel>Max radius from base (km)</FormLabel>
                        <FormControl>
                          <Input type="number" placeholder="150" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <div className="grid gap-4 sm:grid-cols-2">
                    <FormField
                      control={form.control}
                      name="served_regions"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Served regions (one per line)</FormLabel>
                          <FormControl>
                            <Textarea
                              placeholder={"Bavaria\nSchwaben\nOberbayern"}
                              {...field}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="excluded_regions"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Excluded regions (one per line)</FormLabel>
                          <FormControl>
                            <Textarea
                              placeholder={"Outside Germany"}
                              {...field}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Capacity & Contract Size</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 sm:grid-cols-3">
                  <FormField
                    control={form.control}
                    name="min_contract_value_eur"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Min contract value (EUR)</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            placeholder="400000"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="max_contract_value_eur"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Max contract value (EUR)</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            placeholder="4000000"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="partner_threshold_eur"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Needs a partner above (EUR)</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            placeholder="5000000"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Scope & Certifications</CardTitle>
                  <CardDescription>
                    What you do, what you're certified for, and what you can't
                    do for certified/regulatory reasons.
                  </CardDescription>
                </CardHeader>
                <CardContent className="grid gap-4 sm:grid-cols-3">
                  <FormField
                    control={form.control}
                    name="capabilities"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Capabilities (one per line)</FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder={
                              "Road construction\nSewers and pipelines"
                            }
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="certifications"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Certifications (one per line)</FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder={"DB rail qualification"}
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="explicit_exclusions"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Cannot do (one per line)</FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder={"Rail-side work\nBridges"}
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Role & Self-Perform</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 sm:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="contractor_role"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Typical role</FormLabel>
                        <Select
                          onValueChange={field.onChange}
                          value={field.value}
                        >
                          <FormControl>
                            <SelectTrigger className="w-full">
                              <SelectValue placeholder="Select a role" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="main_contractor">
                              Main contractor
                            </SelectItem>
                            <SelectItem value="subcontractor">
                              Subcontractor
                            </SelectItem>
                            <SelectItem value="either">Either</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="max_self_perform_pct"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          Max required self-perform share (%)
                        </FormLabel>
                        <FormControl>
                          <Input type="number" placeholder="40" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Financial Guarantees</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 sm:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="guarantee_limit_total_eur"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Total guarantee limit (EUR)</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            placeholder="1500000"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="guarantee_currently_committed_eur"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          Currently committed guarantees (EUR)
                        </FormLabel>
                        <FormControl>
                          <Input type="number" placeholder="0" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Availability</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 sm:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="available_from"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Free from</FormLabel>
                        <FormControl>
                          <Input type="date" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="capacity_note"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Capacity note</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="Two crews committed until March"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Reference Projects</CardTitle>
                </CardHeader>
                <CardContent>
                  <FormField
                    control={form.control}
                    name="reference_projects"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>What you can show (one per line)</FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder={
                              "€2.9M state road rehabilitation\nDistrict sewer renewal"
                            }
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Custom Hardliners</CardTitle>
                  <CardDescription>
                    Any hard rules specific to your company that aren't captured
                    above — each one becomes a dealbreaker check against future
                    bids.
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  {fields.map((item, index) => (
                    <div key={item.id} className="flex items-center gap-2">
                      <FormField
                        control={form.control}
                        name={`custom_hardliners.${index}.value`}
                        render={({ field }) => (
                          <FormItem className="flex-1">
                            <FormControl>
                              <Input
                                placeholder="We lose on price to the bigger players about half the time"
                                {...field}
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() => remove(index)}
                        disabled={fields.length === 1}
                      >
                        <Trash2 className="size-4" />
                        <span className="sr-only">Remove</span>
                      </Button>
                    </div>
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="self-start"
                    onClick={() => append({ value: "" })}
                  >
                    <Plus className="size-4" />
                    Add hardliner
                  </Button>
                </CardContent>
              </Card>

              <LoadingButton
                type="submit"
                className="w-full"
                loading={mutation.isPending}
              >
                Save company profile
              </LoadingButton>
            </form>
          </Form>
        </div>
      </main>

      <Footer />
    </div>
  )
}
