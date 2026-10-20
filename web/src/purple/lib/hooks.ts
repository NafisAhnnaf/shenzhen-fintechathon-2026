import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAccount } from "wagmi";
import { api, type AppState, type Bill, type LogLine } from "./api";
import { useMe } from "../../lib/hooks";

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

/** The signed-in person's role, as the server decides it (wallet sign-in or email): owner, approver (finance
 * manager), clerk, underwriter (bank), arbiter, or viewer. null while signed out. */
export function useRole() {
  const { address: wallet, isConnected } = useAccount();
  const { data: me } = useMe();
  const role = me && me.role !== "none" && me.role !== "viewer" ? (me.role === "*" ? "owner" : me.role) : null;
  return { address: me?.address ?? wallet, isConnected: isConnected || !!me, role, me };
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
