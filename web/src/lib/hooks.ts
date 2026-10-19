import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AppState, type Bill, type Me, type Notification, type Public } from "./api";

export const usePublic = () => useQuery({ queryKey: ["public"], queryFn: () => api.get<Public>("/public"), staleTime: 60_000 });

/** The signed-in person: their address and role, decided by the server from the deployment record. */
export const useMe = () =>
  useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/auth/me"), retry: false, staleTime: 30_000 });

export const useAppState = () => useQuery({ queryKey: ["state"], queryFn: () => api.get<AppState>("/state"), refetchInterval: 4000 });

export const useBills = () => useQuery({ queryKey: ["bills"], queryFn: () => api.get<Bill[]>("/bills"), refetchInterval: 4000 });

export const useNotifications = () =>
  useQuery({ queryKey: ["notifications"], queryFn: () => api.get<Notification[]>("/notifications"), refetchInterval: 5000 });

/** What the signed-in role may do. Mirrors the server's checks so buttons only show when they would work. */
export function useCan() {
  const { data: me } = useMe();
  const r = me?.role;
  const any = r === "*";
  return {
    role: r,
    staff: any || r === "owner" || r === "approver",
    owner: any || r === "owner",
    manager: any || r === "approver",
    bank: any || r === "underwriter",
    arbiter: any || r === "arbiter",
    protect: any || (!!r && r !== "viewer"),
  };
}

/** A mutation that refreshes everything on screen when it finishes. */
export function useAction<TArgs, TOut>(fn: (a: TArgs) => Promise<TOut>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => qc.invalidateQueries() });
}

export function useSupplierName() {
  const { data } = useAppState();
  return (id?: string | null) => (id && data?.suppliers[id]?.name) || id || "";
}
