// LRM viewer dashboard (web + native). Owns all state: language, source list, selected source/page,
// word-hit selection, and last-source/last-page persistence (see inner/storage.ts for the key scheme).
import React, { useEffect, useState } from 'react';
import { StyleSheet, View, useWindowDimensions } from 'react-native';
import { Appbar } from 'react-native-paper';
import LRMPageDashboardLeftSideBar from './LRMPageDashboardLeftSideBar';
import LRMPageDashboardPageContent from './LRMPageDashboardPageContent';
import { fetchPage, fetchSources, pageImageUrl } from './inner/api';
import { getLastPage, getLastSource, setLastPage, setLastSource } from './inner/storage';
import type { LastSource } from './inner/storage';
import { LANGS } from './inner/types';
import type { Hit, Lang, PageDoc, Source } from './inner/types';

export default function LRMPageDashboard() {
  const { width } = useWindowDimensions();
  const wide = width >= 800;
  const sideW = wide ? width * 0.25 : 0;

  const [lang, setLang] = useState<Lang>('fr');
  const [sources, setSources] = useState<Source[]>([]);
  const [source, setSource] = useState<Source | null>(null);
  const [page, setPage] = useState<PageDoc | null>(null);
  const [n, setN] = useState(1);
  const [input, setInput] = useState('1');
  const [hit, setHit] = useState<Hit | null>(null);
  const [showBoxes, setShowBoxes] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showList, setShowList] = useState(true);
  const [pendingSource, setPendingSource] = useState<LastSource | null>(null);
  const [restored, setRestored] = useState(false);

  // on launch: read which source was open last, and switch to its language -- this kicks off the
  // sources fetch below; the actual selection happens once that list has arrived (see next effect)
  useEffect(() => {
    getLastSource().then(saved => {
      if (saved && LANGS.includes(saved.language)) {
        setPendingSource(saved);
        setLang(saved.language);
      }
      setRestored(true);
    });
  }, []);

  useEffect(() => {
    setSource(null); setPage(null); setError('');
    fetchSources(lang).then(setSources).catch(e => setError(`Cannot reach server: ${e}`));
  }, [lang]);

  // once the restored language's sources have loaded, select the saved one -- selectSource() below
  // looks up that source's own last page (or starts at its first recognised page if none is saved yet). If there is
  // no saved source to restore (first launch, or it's gone from the list), fall back to the 1st source.
  useEffect(() => {
    if (source || sources.length === 0) return;
    if (pendingSource) {
      if (pendingSource.language !== lang) return; // wait for lang state to catch up
      const match = sources.find(s => s.sourceGuid === pendingSource.sourceGuid);
      setPendingSource(null);
      if (match) { selectSource(match); return; }
    } else if (!restored) {
      return; // still waiting on the storage read before deciding to auto-select
    }
    selectSource(sources[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sources, pendingSource, lang, restored, source]);

  useEffect(() => {
    if (!source) return;
    setLoading(true); setError(''); setHit(null);
    fetchPage(source.source_key, n, lang)
      .then(setPage)
      .catch(e => { setPage(null); setError(String(e)); })
      .finally(() => setLoading(false));
  }, [source, n, lang]);

  // persist the current page for the current source on every navigation
  useEffect(() => {
    if (!source) return;
    setLastPage(source.sourceGuid, n);
  }, [source, n]);

  async function selectSource(s: Source) {
    setSource(s);
    await setLastSource({ sourceGuid: s.sourceGuid, source_key: s.source_key, language: lang });
    const saved = await getLastPage(s.sourceGuid);
    const target = saved ?? s.first_page ?? 1; // no page saved yet -> start at its first recognised page
    const clamped = Math.min(Math.max(1, target), s.page_count ?? Infinity);
    setN(clamped); setInput(String(clamped));
    if (!wide) setShowList(false);
  }

  const last = source ? source.page_count ?? Infinity : Infinity;
  const goto = (v: number) => { const p = Math.min(Math.max(1, v || 1), last); setN(p); setInput(String(p)); };

  return (
    <>
      <Appbar.Header elevated>
        {!wide && <Appbar.Action icon="menu" onPress={() => setShowList(v => !v)} />}
        <Appbar.Content title={source ? source.title : 'LRM'}
          subtitle={page ? `page ${page.page}${page.printed_page_number ? ` (printed ${page.printed_page_number})` : ''}` : undefined} />
      </Appbar.Header>
      <View style={styles.row}>
        {(wide || showList) && (
          <LRMPageDashboardLeftSideBar wide={wide} sideWidth={sideW} sources={sources}
            selectedSourceGuid={source?.sourceGuid ?? null} onSelectSource={selectSource} />
        )}
        {(wide || !showList) && (
          <LRMPageDashboardPageContent
            avail={width - sideW - 24} source={source} page={page}
            pageImage={page ? pageImageUrl(page) : null} loading={loading} error={error}
            lang={lang} onLangChange={setLang}
            input={input} onInputChange={setInput} onSubmitPage={() => goto(parseInt(input, 10))}
            onPrev={() => goto(n - 1)} onNext={() => goto(n + 1)} canPrev={n > 1} canNext={n < last}
            showBoxes={showBoxes} onToggleBoxes={setShowBoxes}
            hit={hit} onPick={setHit} onCloseHit={() => setHit(null)}
          />
        )}
      </View>
    </>
  );
}

const styles = StyleSheet.create({ row: { flex: 1, flexDirection: 'row' } });
