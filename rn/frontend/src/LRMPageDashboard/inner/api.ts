// Backend calls for LRMPageDashboard: py/api -> /sources, /page, /files/<image>.
import type { Lang, PageDoc, Source } from './types';

export const API: string = process.env.EXPO_PUBLIC_API_BASE ?? 'http://localhost:8000';

export async function fetchSources(lang: Lang): Promise<Source[]> {
  const r = await fetch(`${API}/sources?language=${lang}`);
  if (!r.ok) throw new Error(`cannot list sources (HTTP ${r.status})`);
  const raw: Array<Omit<Source, 'sourceGuid'> & { source_guid: string }> = await r.json();
  return raw.map(({ source_guid, ...rest }) => ({ ...rest, sourceGuid: source_guid }));
}

export async function fetchPage(sourceKey: string, page: number, lang: Lang): Promise<PageDoc> {
  const r = await fetch(`${API}/page?source=${encodeURIComponent(sourceKey)}&page=${page}&language=${lang}`);
  if (!r.ok) throw new Error(`page ${page} is not available (HTTP ${r.status})`);
  return r.json();
}

export function pageImageUrl(page: PageDoc): string {
  return `${API}/files/${page.image}`;
}
