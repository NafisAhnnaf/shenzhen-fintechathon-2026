import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAccount } from "wagmi";
import { api, type AppState, type Bill, type LogLine } from "./api";
import { roleOf } from "./wallet";

export const useAppState = () =>
  useQuery({ queryKey: ["state"], queryFn: () => api.get<AppState>("/state"), refetchInterval: 3000 });

export const useBills = () =>
  useQuery({ queryKey: ["bills"], queryFn: () => api.get<Bill[]>("/bills"), refetchInterval: 3000 });

export const useLog = (security = false) =>
  useQuery({
    queryKey: ["log", security],
    queryFn: () => api.get<LogLine[]>(`/log?limit=300${security ? "&security=true" : ""}`),
    refetchInterval: 2000,
  });

/** The connected wallet's role in the vault: owner, approver (finance manager), or null. */
export function useRole() {
  const { address, isConnected } = useAccount();
  const { data } = useAppState();
  return { address, isConnected, role: data ? roleOf(address, data.roles) : null };
}

/** A mutation that refreshes everything the desk shows when it finishes. */
export function useAction<TArgs, TOut>(fn: (a: TArgs) => Promise<TOut>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => qc.invalidateQueries(),
  });
}

export function useSupplierName() {
  const { data } = useAppState();
  return (id?: string | null) => (id && data?.suppliers[id]?.name) || id || "";
}
