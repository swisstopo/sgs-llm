import { LitElement, css, html } from 'lit';
import { customElement } from 'lit/decorators.js';
import { ObservableController } from '../lib/ObservableController';
import {
  SUPPORTED_LANGUAGES,
  changeLanguage,
  currentLanguage,
  languageChanged$,
  t,
} from '../i18n/i18n';
import type { AppLanguage } from '../i18n/i18n';

@customElement('sgs-header')
export class SgsHeader extends LitElement {
  static override styles = css`
    :host {
      display: flex;
      align-items: center;
      gap: 1rem;
      padding: 0 1rem;
      height: 3.5rem;
      background: var(--sgc-color-bg--white, #ffffff);
      border-bottom: 1px solid var(--sgc-color-border, #d5dbe0);
    }

    .title {
      font-size: 1.125rem;
      font-weight: 700;
    }

    .title .accent {
      color: var(--sgc-color-brand, #d8232a);
    }

    .subtitle {
      color: var(--sgc-color-text--secondary, #4b5a68);
      font-size: 0.875rem;
    }

    .spacer {
      flex: 1;
    }

    .lang-switcher {
      display: flex;
      gap: 0.25rem;
    }

    .lang-switcher button {
      border: none;
      background: none;
      font: inherit;
      font-size: 0.8125rem;
      padding: 0.25rem 0.5rem;
      border-radius: 0.25rem;
      cursor: pointer;
      color: var(--sgc-color-text--secondary, #4b5a68);
      text-transform: uppercase;
    }

    .lang-switcher button:hover {
      background: var(--sgc-color-bg--grey, #f0f2f4);
    }

    .lang-switcher button[aria-current='true'] {
      color: var(--sgc-color-brand, #d8232a);
      font-weight: 700;
    }
  `;

  private readonly language = new ObservableController(this, languageChanged$);

  override render() {
    const active = this.language.value ?? currentLanguage();
    return html`
      <span class="title"><span class="accent">SGS</span> LLM</span>
      <span class="subtitle">${t('app.subtitle')}</span>
      <span class="spacer"></span>
      <nav class="lang-switcher" aria-label="Language">
        ${SUPPORTED_LANGUAGES.map(
          (lang) => html`
            <button aria-current=${lang === active} @click=${() => this.selectLanguage(lang)}>
              ${lang}
            </button>
          `,
        )}
      </nav>
    `;
  }

  private selectLanguage(lang: AppLanguage): void {
    void changeLanguage(lang);
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-header': SgsHeader;
  }
}
