// LRMPageDashboard subcomponent: the list of sources for the currently chosen language.
import React from 'react';
import { FlatList, StyleSheet } from 'react-native';
import LRMSourceCardForList from './LRMSourceCardForList';
import type { Source } from './inner/types';

type Props = {
  wide: boolean;
  sideWidth: number;
  sources: Source[];
  selectedSourceGuid: string | null;
  onSelectSource: (source: Source) => void;
};

export default function LRMPageDashboardLeftSideBar({ wide, sideWidth, sources, selectedSourceGuid, onSelectSource }: Props) {
  return (
    <FlatList style={wide ? [styles.sidebar, { width: sideWidth, flexGrow: 0, flexShrink: 0 }] : styles.drawer}
      data={sources}
      keyExtractor={s => s.sourceGuid}
      renderItem={({ item }) => (
        <LRMSourceCardForList source={item} selected={selectedSourceGuid === item.sourceGuid} onPress={onSelectSource} />
      )} />
  );
}

const styles = StyleSheet.create({
  sidebar: { borderRightWidth: 1, borderColor: '#ddd' },
  drawer: { flex: 1 },
});
