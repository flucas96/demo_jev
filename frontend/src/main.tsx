import React from 'react';
import ReactDOM from 'react-dom/client';
import { createTheme, MantineProvider } from '@mantine/core';
import '@mantine/core/styles.css';
import '@fontsource-variable/inter';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import './styles.css';
const App = React.lazy(() => import('./App'));
const WaldoPresentation = React.lazy(() => import('./waldo/WaldoPresentation'));
const presentationPage = /^\/waldo\/presentation\/?$/.test(location.pathname);
const WaldoGame = React.lazy(() => import('./waldo/WaldoGame'));
const WaldoReferences = React.lazy(() => import('./waldo/References'));

const waldoPage = /^\/waldo(?:\.html|\/)?$/.test(location.pathname);
const referencePage = /^\/waldo\/referenzen\/?$/.test(location.pathname);

const theme = createTheme({
  fontFamily: 'Inter Variable, sans-serif',
  fontFamilyMonospace: 'IBM Plex Mono, monospace',
  primaryColor: 'vermilion',
  colors: {
    vermilion: ['#fff1ed', '#ffdfd5', '#ffbba7', '#f9947c', '#f2755b', '#e95d43', '#de4b32', '#c53b25', '#ad321f', '#982817'],
  },
  defaultRadius: 'sm',
  headings: { fontFamily: 'Inter Variable, sans-serif', fontWeight: '550' },
  focusRing: 'auto',
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} forceColorScheme="light">
      <React.Suspense fallback={<div role="status" style={{ padding: 32 }}>Loading…</div>}>
        {presentationPage ? <WaldoPresentation /> : referencePage ? <WaldoReferences /> : waldoPage ? <WaldoGame />  : <App />}
      </React.Suspense>
    </MantineProvider>
  </React.StrictMode>,
);
