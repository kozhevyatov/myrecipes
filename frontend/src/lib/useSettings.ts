import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: api.settings.get, staleTime: 60_000 });
}
