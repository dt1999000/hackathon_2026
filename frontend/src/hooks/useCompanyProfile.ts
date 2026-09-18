import { useQuery } from "@tanstack/react-query"
import { AxiosError } from "axios"

import {
  CompanyProfileService,
  type CompanyProfilePublic,
} from "@/client"
import { isLoggedIn } from "@/hooks/useAuth"

export const COMPANY_PROFILE_QUERY_KEY = ["companyProfile"] as const

function isNotFoundError(error: unknown): boolean {
  return error instanceof AxiosError && error.response?.status === 404
}

export function useCompanyProfile() {
  return useQuery<CompanyProfilePublic | null, Error>({
    queryKey: COMPANY_PROFILE_QUERY_KEY,
    queryFn: async () => {
      try {
        return (await CompanyProfileService.profileReadCompanyProfileMe())
          .data
      } catch (error) {
        if (isNotFoundError(error)) {
          return null
        }
        throw error
      }
    },
    enabled: isLoggedIn(),
  })
}
