import { useQuery } from '@tanstack/react-query'
import { api } from './api'

/** Server capabilities (fake platforms, Nango); fetched once per page load. */
export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: api.health, staleTime: Infinity })
}
