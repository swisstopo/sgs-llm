import '@swissgeol/ui-core/import';
import '@swissgeol/ui-core/styles.css';
import 'ol/ol.css';
import './style/theme.css';
import './style/global.css';
import { loadRuntimeConfig } from './config';
import { initI18n } from './i18n/i18n';
import { registerProjections } from './lib/projection';

async function bootstrap(): Promise<void> {
  registerProjections();
  await Promise.all([loadRuntimeConfig(), initI18n()]);
  await import('./components/sgs-app');
}

void bootstrap();
