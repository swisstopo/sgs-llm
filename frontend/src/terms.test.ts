import { describe, expect, it } from 'vitest';
import { SUPPORTED_LANGUAGES } from './i18n/i18n';
import { TERMS_URLS, termsUrl } from './terms';

describe('localized terms URLs', () => {
  it('provides an official URL in every supported website language', () => {
    expect(Object.keys(TERMS_URLS).sort()).toEqual([...SUPPORTED_LANGUAGES].sort());
    for (const language of SUPPORTED_LANGUAGES) {
      expect(termsUrl(language)).toMatch(
        new RegExp(`^https://www\\.admin\\.ch/${language}/[^/]+$`),
      );
    }
  });
});
