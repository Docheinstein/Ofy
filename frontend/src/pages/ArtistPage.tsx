import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Loader2, User } from "lucide-react";
import { useState } from "react";
import { api, coverUrl, type ArtistDetail } from "@/lib/api";
import { AlbumCard } from "@/components/AlbumCard";
import { Button } from "@/components/ui/button";

export function ArtistPage() {
  const { id } = useParams();
  const { data, isLoading, error } = useQuery({
    queryKey: ["artist", id],
    queryFn: () => api.get<ArtistDetail>(`/api/artist/${id}`),
  });
  if (isLoading) return <div className="flex h-64 items-center justify-center"><Loader2 className="animate-spin" /></div>;
  if (error || !data) return <div className="p-8 text-destructive">{(error as Error)?.message}</div>;
  const years = [data.life_span?.begin?.slice(0, 4), data.life_span?.end?.slice(0, 4)].filter(Boolean).join("–");

  return (
    <div>
      <header className="relative flex h-72 items-end gap-6 overflow-hidden bg-gradient-to-b from-neutral-600/60 to-surface p-6">
        {data.image_release_group && (
          <img src={coverUrl("release-group", data.image_release_group, 1200)} alt="" className="absolute inset-0 h-full w-full scale-110 object-cover opacity-30 blur-2xl" />
        )}
        <div className="relative flex h-44 w-44 shrink-0 items-center justify-center overflow-hidden rounded-full bg-elevated shadow-2xl">
          {data.image_release_group ? (
            <img src={coverUrl("release-group", data.image_release_group, 500)} className="h-full w-full object-cover" alt="" />
          ) : (
            <User className="h-16 w-16 text-muted-foreground" />
          )}
        </div>
        <div className="relative min-w-0">
          <p className="text-sm font-semibold">{data.type ?? "Artist"}</p>
          <h1 className="truncate text-5xl font-black tracking-tight md:text-7xl" data-testid="artist-name">{data.name}</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            {[data.country, years, data.disambiguation, data.genres.slice(0, 3).join(", ")].filter(Boolean).join(" · ")}
          </p>
        </div>
      </header>

      <div className="space-y-10 p-6">
        {data.discography.map((bucket) => <Bucket key={bucket.type} bucket={bucket} />)}

        {data.related.length > 0 && (
          <section>
            <h2 className="mb-3 text-2xl font-bold">Related artists</h2>
            <div className="flex flex-wrap gap-2">
              {data.related.map((r) => (
                <Link key={r.id} to={`/artist/${r.id}`} className="rounded-full bg-elevated px-4 py-2 text-sm hover:bg-accent">
                  <span className="font-semibold">{r.name}</span>
                  <span className="ml-2 text-xs text-muted-foreground">{r.relation}</span>
                </Link>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function Bucket({ bucket }: { bucket: ArtistDetail["discography"][number] }) {
  const [all, setAll] = useState(false);
  const items = all ? bucket.items : bucket.items.slice(0, 12);
  return (
    <section data-testid={`bucket-${bucket.type}`}>
      <div className="mb-2 flex items-end justify-between">
        <h2 className="text-2xl font-bold">{bucket.type === "Album" ? "Albums" : bucket.type === "Single/EP" ? "Singles & EPs" : bucket.type === "Compilation" ? "Compilations" : bucket.type}</h2>
        {bucket.items.length > 12 && (
          <Button variant="link" className="text-muted-foreground" onClick={() => setAll(!all)}>
            {all ? "Show less" : `Show all ${bucket.items.length}`}
          </Button>
        )}
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-1">
        {items.map((rg) => <AlbumCard key={rg.id} rg={rg} subtitle={[rg.year, rg.primary_type].filter(Boolean).join(" • ")} />)}
      </div>
    </section>
  );
}
