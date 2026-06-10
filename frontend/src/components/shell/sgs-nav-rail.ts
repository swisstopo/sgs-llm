import { LitElement, css, html } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { consume } from '@lit/context';
import type { TemplateResult } from 'lit';
import { uiServiceContext } from '../../context';
import type { PanelId, UiService } from '../../services/UiService';
import { ObservableController } from '../../lib/ObservableController';
import {
  SUPPORTED_LANGUAGES,
  changeLanguage,
  currentLanguage,
  languageChanged$,
  t,
} from '../../i18n/i18n';
import type { AppLanguage } from '../../i18n/i18n';
import { aboutIcon, catalogIcon, chatIcon, feedbackIcon, languageIcon, mapsIcon } from './icons';

interface RailItem {
  id: PanelId;
  icon: TemplateResult;
  labelKey: string;
}

const RAIL_ITEMS: RailItem[] = [
  { id: 'chat', icon: chatIcon, labelKey: 'rail.chat' },
  { id: 'maps', icon: mapsIcon, labelKey: 'rail.maps' },
  { id: 'catalog', icon: catalogIcon, labelKey: 'rail.catalog' },
  { id: 'feedback', icon: feedbackIcon, labelKey: 'rail.feedback' },
  { id: 'about', icon: aboutIcon, labelKey: 'rail.about' },
];

/**
 * Vertical icon rail on the left edge (SwissGeo style): one button per
 * flyout panel, plus an inline language selector at the bottom.
 */
@customElement('sgs-nav-rail')
export class SgsNavRail extends LitElement {
  static override styles = css`
    :host {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.375rem;
      padding: 0.625rem 0;
      background: var(--sgc-color-bg--white);
      border-right: 1px solid var(--sgc-color-border);
    }

    button {
      display: grid;
      place-items: center;
      width: 2.5rem;
      height: 2.5rem;
      border: none;
      border-radius: 0.375rem;
      background: none;
      color: var(--sgc-color-text--secondary);
      cursor: pointer;
    }

    button:hover {
      background: var(--sgc-color-bg--grey);
      color: var(--sgc-color-text);
    }

    button[aria-pressed='true'] {
      background: var(--sgc-color-brand);
      color: #ffffff;
    }

    .spacer {
      flex: 1;
    }

    .lang-list {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.125rem;
      overflow: hidden;
      max-height: 0;
      opacity: 0;
      transition:
        max-height var(--sgs-motion-duration--fast) var(--sgs-motion-ease),
        opacity var(--sgs-motion-duration--fast) var(--sgs-motion-ease);
    }

    .lang-list.open {
      max-height: 8rem;
      opacity: 1;
    }

    @media (prefers-reduced-motion: reduce) {
      .lang-list {
        transition: none;
      }
    }

    .lang-list button {
      width: 2.5rem;
      height: 1.75rem;
      font: inherit;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
    }

    .lang-list button[aria-current='true'] {
      background: none;
      color: var(--sgc-color-brand);
    }

    button.lang-toggle[aria-expanded='true'] {
      background: var(--sgc-color-bg--grey);
      color: var(--sgc-color-text);
    }
  `;

  @consume({ context: uiServiceContext })
  private uiService!: UiService;

  @state() private languageOpen = false;

  private activePanel?: ObservableController<PanelId | null>;

  private readonly _language = new ObservableController(this, languageChanged$);

  override connectedCallback(): void {
    super.connectedCallback();
    this.activePanel ??= new ObservableController(this, this.uiService.activePanel$);
  }

  override render() {
    const active = this.activePanel?.value ?? this.uiService.activePanel;
    return html`
      ${RAIL_ITEMS.map(
        (item) => html`
          <button
            aria-pressed=${item.id === active}
            title=${t(item.labelKey)}
            aria-label=${t(item.labelKey)}
            @click=${() => this.uiService.togglePanel(item.id)}
          >
            ${item.icon}
          </button>
        `,
      )}
      <span class="spacer"></span>
      <div class="lang-list ${this.languageOpen ? 'open' : ''}" ?inert=${!this.languageOpen}>
        ${SUPPORTED_LANGUAGES.map(
          (lang) => html`
            <button
              aria-current=${lang === currentLanguage()}
              @click=${() => this.selectLanguage(lang)}
            >
              ${lang}
            </button>
          `,
        )}
      </div>
      <button
        class="lang-toggle"
        aria-expanded=${this.languageOpen}
        title=${t('rail.language')}
        aria-label=${t('rail.language')}
        @click=${() => (this.languageOpen = !this.languageOpen)}
      >
        ${languageIcon}
      </button>
    `;
  }

  private selectLanguage(lang: AppLanguage): void {
    this.languageOpen = false;
    void changeLanguage(lang);
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-nav-rail': SgsNavRail;
  }
}
