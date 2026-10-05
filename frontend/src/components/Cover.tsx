import { useState } from "react";
import { Disc3 } from "lucide-react";
import { cn } from "@/lib/utils";

export function Cover({ src, alt, className, rounded = "rounded-md" }: { src?: string; alt?: string; className?: string; rounded?: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className={cn("relative aspect-square overflow-hidden bg-elevated shadow-lg shadow-black/40", rounded, className)}>
      {src && !failed ? (
        <img src={src} alt={alt ?? ""} loading="lazy" className="h-full w-full object-cover" onError={() => setFailed(true)} />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-muted-foreground">
          <Disc3 className="h-1/3 w-1/3" />
        </div>
      )}
    </div>
  );
}
