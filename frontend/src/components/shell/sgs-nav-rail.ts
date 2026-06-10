import { LitElement, css, html, nothing } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { consume } from '@lit/context';
import type { TemplateResult } from 'lit';
import { layerServiceContext, uiServiceContext } from '../../context';
import type { PanelId, UiService } from '../../services/UiService';
import type { LayerService, MapLayerState } from '../../services/LayerService';
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
      position: relative;
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

    .badge {
      position: absolute;
      top: 0.125rem;
      right: 0.125rem;
      min-width: 1rem;
      height: 1rem;
      padding: 0 0.25rem;
      box-sizing: border-box;
      display: grid;
      place-items: center;
      border-radius: 999px;
      background: var(--sgc-color-border);
      color: var(--sgc-color-text);
      font-size: 0.6875rem;
      font-weight: 700;
      line-height: 1;
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

  @consume({ context: layerServiceContext })
  private layerService!: LayerService;

  @state() private languageOpen = false;

  private activePanel?: ObservableController<PanelId | null>;

  private layers?: ObservableController<MapLayerState[]>;

  /** Last displayed-layer count, used to fire the badge "pop" only on add. */
  private previousCount = 0;

  private readonly _language = new ObservableController(this, languageChanged$);

  override connectedCallback(): void {
    super.connectedCallback();
    this.activePanel ??= new ObservableController(this, this.uiService.activePanel$);
    this.layers ??= new ObservableController(this, this.layerService.layers$);
  }

  override render() {
    const active = this.activePanel?.value ?? this.uiService.activePanel;
    const count = this.layers?.value?.length ?? 0;
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
            ${item.id === 'maps' && count > 0 ? html`<span class="badge">${count}</span>` : nothing}
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

  override updated(): void {
    const count = this.layers?.value?.length ?? 0;
    if (count > this.previousCount) {
      this.bumpBadge();
    }
    this.previousCount = count;
  }

  /** One-shot "pop" on the maps badge when a layer is added. */
  private bumpBadge(): void {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return;
    }
    this.renderRoot
      .querySelector('.badge')
      ?.animate(
        [{ transform: 'scale(1)' }, { transform: 'scale(1.4)' }, { transform: 'scale(1)' }],
        { duration: 320, easing: 'cubic-bezier(0.2, 0, 0, 1)' },
      );
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
