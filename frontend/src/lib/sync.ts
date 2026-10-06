import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type SyncKind, type SyncSelectionItem } from "./api";

export interface SyncTarget {
  kind: SyncKind;
  id: string;
  title: string;
  subtitle?: string;
}

/** What's selected to be kept on the sync remote. A selected artist/album covers everything below it. */
export function useSyncSelection() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["sync-selection"],
    queryFn: () => api.get<SyncSelectionItem[]>("/api/sync/selection"),
    staleTime: 60_000,
  });
  const items = data ?? [];
  const ids = (k: SyncKind) => new Set(items.filter((i) => i.kind === k).map((i) => i.ref_id));
  const artists = ids("artist");
  const albums = ids("album");
  const tracks = ids("track");

  const toggle = useMutation({
    mutationFn: ({ target, selected }: { target: SyncTarget; selected: boolean }) =>
      api.put("/api/sync/selection", {
        kind: target.kind, id: target.id, selected, title: target.title, subtitle: target.subtitle ?? "",
      }),
    onMutate: async ({ target, selected }) => {
      await qc.cancelQueries({ queryKey: ["sync-selection"] });
      qc.setQueryData<SyncSelectionItem[]>(["sync-selection"], (old = []) =>
        selected
          ? [...old, { kind: target.kind, ref_id: target.id, title: target.title, subtitle: target.subtitle ?? "", created_at: Date.now() / 1000 }]
          : old.filter((i) => !(i.kind === target.kind && i.ref_id === target.id)),
      );
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["sync-selection"] });
      qc.invalidateQueries({ queryKey: ["sync-summary"] });
    },
  });

  return {
    items,
    has: (kind: SyncKind, id: string | null | undefined) =>
      !!id && (kind === "artist" ? artists : kind === "album" ? albums : tracks).has(id),
    /** The ancestor that already brings this item along, if any. */
    inheritedFrom: (artistId?: string | null, releaseId?: string | null): "artist" | "album" | null =>
      releaseId && albums.has(releaseId) ? "album" : artistId && artists.has(artistId) ? "artist" : null,
    set: (target: SyncTarget, selected: boolean) => toggle.mutate({ target, selected }),
  };
}
