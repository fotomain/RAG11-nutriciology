// AsyncStorage key scheme for LRMPageDashboard.
//
// - "lastSource"            -> LastSource JSON: which source (by sourceGuid) was open last; read once on
//                              app start to know what to reopen.
// - "pageNumber-<sourceGuid>" -> page number last viewed IN THAT SOURCE. Each source remembers its own last
//                              page independently. If a source has no such key yet (e.g. never opened before),
//                              callers fall back to page 1.
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { Lang } from './types';

export type LastSource = { sourceGuid: string; source_key: string; language: Lang };

const LAST_SOURCE_KEY = 'lastSource';
const pageNumberKey = (sourceGuid: string) => `pageNumber-${sourceGuid}`;

export async function getLastSource(): Promise<LastSource | null> {
  try {
    const raw = await AsyncStorage.getItem(LAST_SOURCE_KEY);
    return raw ? (JSON.parse(raw) as LastSource) : null;
  } catch {
    return null; // corrupt/unavailable storage -- behave as if nothing was saved
  }
}

export async function setLastSource(v: LastSource): Promise<void> {
  try {
    await AsyncStorage.setItem(LAST_SOURCE_KEY, JSON.stringify(v));
  } catch { /* best-effort persistence */ }
}

export async function getLastPage(sourceGuid: string): Promise<number | null> {
  try {
    const raw = await AsyncStorage.getItem(pageNumberKey(sourceGuid));
    const n = raw ? parseInt(raw, 10) : NaN;
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
}

export async function setLastPage(sourceGuid: string, page: number): Promise<void> {
  try {
    await AsyncStorage.setItem(pageNumberKey(sourceGuid), String(page));
  } catch { /* best-effort persistence */ }
}
