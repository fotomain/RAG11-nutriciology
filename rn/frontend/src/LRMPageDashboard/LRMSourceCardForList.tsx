// LRMPageDashboard subcomponent: a single source card rendered inside LRMPageDashboardLeftSideBar's FlatList.
import React from 'react';
import { StyleSheet } from 'react-native';
import { Card, Text } from 'react-native-paper';
import type { Source } from './inner/types';

type Props = {
  source: Source;
  selected: boolean;
  onPress: (source: Source) => void;
};

export default function LRMSourceCardForList({ source, selected, onPress }: Props) {
  return (
    <Card style={[styles.card, selected ? styles.active : undefined]} onPress={() => onPress(source)}>
      <Card.Title title={source.title}
        subtitle={source.recognised_pages ? `${source.recognised_pages} / ${source.page_count} pages` : undefined} />
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { marginHorizontal: 8, marginVertical: 4 },
  active: { backgroundColor: '#e8f0fe' },
});
