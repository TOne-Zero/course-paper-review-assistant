import React from 'react';
import ReactDOM from 'react-dom/client';
import '@fontsource-variable/noto-serif-sc';
import '@fontsource-variable/inter';
import './styles.css';
import App from './App';

const initialUrl = new URL(location.href);
if (initialUrl.searchParams.get('preview') === 'criteria') {
  initialUrl.searchParams.delete('preview'); initialUrl.searchParams.set('view', 'workspace'); initialUrl.searchParams.set('settings', 'criteria');
  history.replaceState(null, '', initialUrl);
}
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
