export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  put: <T>(p: string, b: unknown) => request<T>("PUT", p, b),
  del: <T>(p: string) => request<T>("DELETE", p),
};

export interface Settings {
  library_path: string;
  output_format: "mp3" | "m4a" | "opus";
  mp3_quality: "320" | "v0";
  path_template: string;
  concurrency: number;
  match_threshold: number;
  lyrics_fetch: boolean;
  lyrics_prefer_synced: boolean;
  lyrics_embed: boolean;
  lrclib_url: string;
  cookies_path: string;
  max_retries: number;
}

export type TrackStatus = "none" | "queued" | "downloading" | "done" | "failed" | "needs_review";
export type LyricsStatus = "none" | "synced" | "plain" | "instrumental" | "not_found";
export type AlbumStatus = "none" | "partial" | "complete";

export interface AlbumLibrary {
  status: AlbumStatus;
  total: number;
  done: number;
  active: number;
  failed: number;
  needs_review: number;
  release_id?: string;
}

export interface ReleaseGroupSummary {
  id: string;
  title: string;
  primary_type: string | null;
  secondary_types: string[];
  first_release_date: string | null;
  year: string | null;
  artist: string;
  artist_id: string | null;
  library?: AlbumLibrary | null;
}

export interface ArtistSummary {
  id: string;
  name: string;
  sort_name?: string;
  type?: string | null;
  country?: string | null;
  disambiguation?: string | null;
  genres: string[];
  life_span?: { begin?: string; end?: string; ended?: boolean };
}

export interface ArtistDetail extends ArtistSummary {
  image_release_group: string | null;
  wikidata_id: string | null;
  discography: { type: string; items: ReleaseGroupSummary[] }[];
  related: { id: string; name: string; disambiguation: string | null; relation: string }[];
}

export interface TrackHit {
  id: string;
  title: string;
  artist: string;
  artist_id: string | null;
  length_ms: number | null;
  disambiguation: string | null;
  release: { id: string; title: string; release_group_id: string | null; date: string | null } | null;
}

export interface SearchResult {
  artists?: ArtistSummary[];
  albums?: ReleaseGroupSummary[];
  tracks?: TrackHit[];
}

export interface Edition {
  id: string;
  title: string;
  status: string | null;
  date: string | null;
  country: string | null;
  formats: string[];
  track_count: number;
  disambiguation: string | null;
  barcode?: string | null;
  labels: string[];
  catalog_numbers: string[];
}

export interface ReleaseGroupDetail extends ReleaseGroupSummary {
  genres: string[];
  canonical_release_id: string;
  selected_release_id: string;
  editions: Edition[];
}

export interface TrackState {
  status: TrackStatus;
  lyrics_status: LyricsStatus;
  progress: number;
  stage: string | null;
  error?: string | null;
  match_score?: number | null;
  match_source?: string | null;
  video_id?: string | null;
  file_path?: string | null;
  file_format?: string | null;
}

export interface TrackRowData {
  track_id: string;
  recording_id: string;
  disc: number;
  disc_total: number;
  position: number;
  number: string;
  track_total: number;
  title: string;
  artist: string;
  length_ms: number | null;
  medium_format: string | null;
  medium_title: string | null;
  library: TrackState;
}

export interface ReleaseDetail extends Edition {
  artist: string;
  artist_id: string | null;
  release_group_id: string;
  release_group_title: string;
  primary_type: string | null;
  first_release_date: string | null;
  length_ms: number;
  tracks: TrackRowData[];
  library: AlbumLibrary;
}

export interface Candidate {
  video_id: string;
  title: string;
  artists: string[];
  album: string | null;
  duration: number | null;
  score: number;
  source: string;
  video_type: string | null;
  thumbnail?: string | null;
}

export interface TrackDetail {
  track_id: string;
  recording_id: string;
  release_id: string;
  release_group_id: string;
  title: string;
  artist: string;
  disc: number;
  position: number;
  length_ms: number | null;
  status: TrackStatus;
  stage: string | null;
  progress: number;
  error: string | null;
  file_path: string | null;
  file_format: string | null;
  lyrics_status: LyricsStatus;
  lyrics_path: string | null;
  lyrics_text: string | null;
  video_id: string | null;
  match_score: number | null;
  match_source: string | null;
  candidates: Candidate[];
  tags: Record<string, string[]> | null;
  threshold: number;
}

export interface LibraryAlbum {
  release_id: string;
  release_group_id: string;
  title: string;
  artist: string;
  artist_id: string | null;
  year: string | null;
  track_count: number;
  folder: string | null;
  library: AlbumLibrary;
  lyrics: Record<string, number>;
}

export interface DownloadItem {
  job_id: number | null;
  kind: string;
  track_id: string | null;
  release_id: string | null;
  release_group_id: string | null;
  title: string;
  artist: string;
  album: string | null;
  status: string;
  track_status: TrackStatus | null;
  stage: string | null;
  progress: number;
  error: string | null;
  attempts: number;
  updated_at: number;
}

export interface TrackEvent {
  type: "track";
  track_id: string;
  release_id: string;
  recording_id: string;
  status: TrackStatus;
  stage: string | null;
  progress: number;
  lyrics_status: LyricsStatus;
  error: string | null;
}

export const coverUrl = (kind: "release" | "release-group", id: string, size: 250 | 500 | 1200 = 500, fallbackRg?: string) =>
  `/api/cover/${kind}/${id}?size=${size}${fallbackRg ? `&fallback_rg=${fallbackRg}` : ""}`;

export const artistImageUrl = (id: string, size: 250 | 500 | 1200 = 500, fallbackRg?: string, wikidata?: string) =>
  `/api/artist-image/${id}?size=${size}${fallbackRg ? `&fallback_rg=${fallbackRg}` : ""}${wikidata ? `&wikidata=${wikidata}` : ""}`;
