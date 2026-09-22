// LRMPageDashboard subcomponent: language/page-nav controls + the page image with tappable word boxes.
import React from 'react';
import { Image, Pressable, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import {
  ActivityIndicator, Divider, IconButton, Modal, Portal, SegmentedButtons, Switch, Text, TextInput,
} from 'react-native-paper';
import { LANGS } from './inner/types';
import type { Block, Hit, Lang, PageDoc, Source } from './inner/types';

const r4 = (v: number) => Math.round(v * 10000) / 10000;

function WordModal({ hit, page, onClose }: { hit: Hit | null; page: PageDoc; onClose: () => void }) {
  const { height } = useWindowDimensions();
  if (!hit) return null;
  const { block, word } = hit;
  const { width: iw, height: ih } = page.image_size;
  return (
    <Portal>
      <Modal visible onDismiss={onClose} contentContainerStyle={[styles.modal, { maxHeight: height * 0.9 }]}>
        <View style={styles.modalHead}>
          <Text variant="headlineSmall" selectable style={{ flexShrink: 1 }}>{word.text}</Text>
          <IconButton icon="close" onPress={onClose} />
        </View>
        <ScrollView>
          <Text selectable style={styles.mono}>
            {`${word.text} · lang ${word.lang} · style ${word.style} · id ${word.id}\n` +
              `page ${page.page} → block ${block.id} (${block.type}, order ${block.reading_order})\n` +
              `bbox: x ${r4(word.bbox.x)} y ${r4(word.bbox.y)} w ${r4(word.bbox.w)} h ${r4(word.bbox.h)}\n` +
              `pixels ${iw}×${ih}: x ${Math.round(word.bbox.x * iw)} y ${Math.round(word.bbox.y * ih)}`}
          </Text>
          <Text variant="titleSmall" style={styles.gap}>Block text</Text>
          <Text selectable style={styles.blockText}>
            {block.text.slice(0, word.char_start)}
            <Text style={styles.hl}>{block.text.slice(word.char_start, word.char_end)}</Text>
            {block.text.slice(word.char_end)}
          </Text>
        </ScrollView>
      </Modal>
    </Portal>
  );
}

function PageImageView({ page, pageImage, avail, onPick, showBoxes, selected }: {
  page: PageDoc; pageImage: string; avail: number; onPick: (h: Hit) => void; showBoxes: boolean; selected: string | null;
}) {
  const W = Math.min(avail, 1000);
  const H = (W * page.image_size.height) / page.image_size.width;
  return (
    <View style={{ width: W, height: H }}>
      <Image source={{ uri: pageImage }} style={{ width: W, height: H }} resizeMode="stretch" />
      {page.blocks.flatMap((block: Block) => block.words.map(word => (
        <Pressable key={word.id} onPress={() => onPick({ block, word })} accessibilityLabel={word.text}
          style={s => [styles.word,
            { left: word.bbox.x * W, top: word.bbox.y * H, width: word.bbox.w * W, height: word.bbox.h * H },
            showBoxes && styles.wordDebug, (s as { hovered?: boolean }).hovered && styles.wordHover,
            word.id === selected && styles.wordOn]} />
      )))}
    </View>
  );
}

export type LRMPageDashboardPageContentProps = {
  avail: number;
  source: Source | null;
  page: PageDoc | null;
  pageImage: string | null;
  loading: boolean;
  error: string;
  lang: Lang;
  onLangChange: (l: Lang) => void;
  input: string;
  onInputChange: (v: string) => void;
  onSubmitPage: () => void;
  onPrev: () => void;
  onNext: () => void;
  canPrev: boolean;
  canNext: boolean;
  showBoxes: boolean;
  onToggleBoxes: (v: boolean) => void;
  hit: Hit | null;
  onPick: (h: Hit) => void;
  onCloseHit: () => void;
};

export default function LRMPageDashboardPageContent({
  avail, source, page, pageImage, loading, error, lang, onLangChange, input, onInputChange, onSubmitPage,
  onPrev, onNext, canPrev, canNext, showBoxes, onToggleBoxes, hit, onPick, onCloseHit,
}: LRMPageDashboardPageContentProps) {
  return (
    <ScrollView style={{ flex: 1 }} contentContainerStyle={styles.body}>
      <View style={styles.controls}>
        <SegmentedButtons value={lang} onValueChange={v => onLangChange(v as Lang)} density="small" style={styles.langSwitch}
          buttons={LANGS.map(l => ({ value: l, label: l.toUpperCase() }))} />
        {source && (
          <View style={styles.pageNav}>
            <IconButton icon="chevron-left" disabled={!canPrev} onPress={onPrev} />
            <TextInput dense mode="outlined" value={input} keyboardType="number-pad" style={{ width: 80 }}
              onChangeText={t => onInputChange(t.replace(/[^0-9]/g, ''))} onSubmitEditing={onSubmitPage} />
            <Text>/ {source.page_count ?? '?'}</Text>
            <IconButton icon="chevron-right" disabled={!canNext} onPress={onNext} />
            <Text>Boxes</Text><Switch value={showBoxes} onValueChange={onToggleBoxes} />
          </View>
        )}
      </View>
      <Divider style={styles.gap} />
      {loading && <ActivityIndicator style={styles.gap} />}
      {!!error && <Text style={styles.error}>{error}</Text>}
      {!source && !error && <Text style={styles.gap}>Select a source.</Text>}
      {page && pageImage && !loading && (
        <View style={styles.pageWrap}>
          <PageImageView page={page} pageImage={pageImage} avail={avail} onPick={onPick} showBoxes={showBoxes}
            selected={hit?.word.id ?? null} />
        </View>
      )}
      {page && <WordModal hit={hit} page={page} onClose={onCloseHit} />}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  controls: { flexDirection: 'row', alignItems: 'center', gap: 24, flexWrap: 'wrap', justifyContent: 'center' },
  langSwitch: { minWidth: 210 },
  pageNav: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap', justifyContent: 'center' },
  body: { padding: 12, alignItems: 'center' },
  gap: { marginTop: 12 },
  error: { color: '#B00020', marginTop: 12 },
  pageWrap: { marginTop: 8, borderWidth: 1, borderColor: '#ddd', backgroundColor: '#fff' },
  word: { position: 'absolute' },
  wordDebug: { borderWidth: 1, borderColor: 'rgba(0,120,255,0.55)' },
  wordHover: { backgroundColor: 'rgba(255,235,59,0.30)' },
  wordOn: { backgroundColor: 'rgba(255,235,59,0.55)', borderWidth: 1, borderColor: '#F9A825' },
  modal: { backgroundColor: '#fff', margin: 16, padding: 16, borderRadius: 12, alignSelf: 'center', width: '92%', maxWidth: 900 },
  modalHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  mono: { fontFamily: 'Courier', fontSize: 12 },
  blockText: { fontSize: 15, lineHeight: 22 },
  hl: { backgroundColor: '#FFEB3B' },
});
