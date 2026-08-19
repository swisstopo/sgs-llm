import '@swissgeol/ui-core/import';
import '@swissgeol/ui-core/styles.css';
import 'ol/ol.css';
import './style/theme.css';
import './style/global.css';
import { loadRuntimeConfig } from './config';
import { initI18n } from './i18n/i18n';
import { registerProjections } from './lib/projection';

async function bootstrap(): Promise<void> {
  await Promise.all([loadRuntimeConfig(), initI18n()]);
  if (window.location.pathname === '/admin' || window.location.pathname.startsWith('/admin/')) {
    document.querySelector('sgs-app')?.remove();
    const admin = document.createElement('sgs-admin-app');
    document.body.append(admin);
    await import('./admin/sgs-admin-app');
    return;
  }
  registerProjections();
  await import('./components/sgs-app');
}

void bootstrap();
