// LRM viewer entry point (Expo / React Native / react-native-paper) -- web + native.
// All state and layout live in ./src/LRMPageDashboard; this file only sets up the Paper theme.
import React from 'react';
import { MD3LightTheme, PaperProvider } from 'react-native-paper';
import LRMPageDashboard from './src/LRMPageDashboard/LRMPageDashboard';

export default function App() {
  return (
    <PaperProvider theme={MD3LightTheme}>
      <LRMPageDashboard />
    </PaperProvider>
  );
}
