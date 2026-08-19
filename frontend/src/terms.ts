import type { AppLanguage } from './i18n/i18n';

/** Official Federal Administration legal-information page for each supported language. */
export const TERMS_URLS: Readonly<Record<AppLanguage, string>> = {
  de: 'https://www.admin.ch/de/rechtliches',
  fr: 'https://www.admin.ch/fr/conditions-utilisation',
  it: 'https://www.admin.ch/it/basi-legali',
  en: 'https://www.admin.ch/en/terms-and-conditions',
  rm: 'https://www.admin.ch/rm/infurmaziuns-giuridicas',
};

export function termsUrl(language: AppLanguage): string {
  return TERMS_URLS[language];
}
