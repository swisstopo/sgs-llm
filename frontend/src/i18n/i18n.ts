import i18next from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { Subject } from 'rxjs';
import type { Observable } from 'rxjs';
import de from './locales/de.json';
import fr from './locales/fr.json';
import it from './locales/it.json';
import en from './locales/en.json';

/** Languages supported by the UI and passed to the Swisstopo APIs. */
export const SUPPORTED_LANGUAGES = ['de', 'fr', 'it', 'en'] as const;
export type AppLanguage = (typeof SUPPORTED_LANGUAGES)[number];

const languageChangedSubject = new Subject<AppLanguage>();

/** Emits whenever the UI language changes; components re-render through it. */
export const languageChanged$: Observable<AppLanguage> = languageChangedSubject.asObservable();

export async function initI18n(): Promise<void> {
  await i18next.use(LanguageDetector).init({
    fallbackLng: 'de',
    supportedLngs: [...SUPPORTED_LANGUAGES],
    resources: {
      de: { translation: de },
      fr: { translation: fr },
      it: { translation: it },
      en: { translation: en },
    },
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: 'sgs-llm.lang',
    },
  });
  i18next.on('languageChanged', () => languageChangedSubject.next(currentLanguage()));
}

export function currentLanguage(): AppLanguage {
  const lang = i18next.language?.slice(0, 2) as AppLanguage | undefined;
  return lang && SUPPORTED_LANGUAGES.includes(lang) ? lang : 'de';
}

export async function changeLanguage(lang: AppLanguage): Promise<void> {
  await i18next.changeLanguage(lang);
}

export const t = i18next.t.bind(i18next);
