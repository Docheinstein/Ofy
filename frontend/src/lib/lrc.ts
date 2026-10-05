export interface LrcLine {
  time: number;
  text: string;
}

export function parseLrc(lrc: string): LrcLine[] {
  const out: LrcLine[] = [];
  for (const raw of lrc.split(/\r?\n/)) {
    const tags = [...raw.matchAll(/\[(\d+):(\d+(?:\.\d+)?)\]/g)];
    if (!tags.length) continue;
    const text = raw.replace(/\[[^\]]*\]/g, "").trim();
    for (const t of tags) out.push({ time: Number(t[1]) * 60 + Number(t[2]), text });
  }
  return out.sort((a, b) => a.time - b.time);
}
