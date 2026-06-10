import { LitElement, css, html } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { Task } from '@lit/task';
import { catalogServiceContext } from '../../context';
import type { CatalogService } from '../../services/CatalogService';
import { ObservableController } from '../../lib/ObservableController';
import { currentLanguage, languageChanged$, t } from '../../i18n/i18n';
import { closeIcon } from '../shell/icons';
import './sgs-legend-content';

/**
 * Modal with the official layer information page (abstract, legend, data
 * owner, geocat/download links) — the Swisstopo legend fragment rendered by
 * sgs-legend-content. Opened via UiService.openLayerInfo; emits `sgs-close`.
 */
@customElement('sgs-layer-info-dialog')
export class SgsLayerInfoDialog extends LitElement {
  static override styles = css`
    dialog {
      width: min(36rem, calc(100vw - 2rem));
      max-height: min(80vh, 44rem);
      padding: 0;
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.5rem;
      box-shadow: 0 8px 32px rgb(0 0 0 / 0.35);
      display: grid;
      grid-template-rows: auto 1fr;
      color: var(--sgc-color-text);
    }

    dialog::backdrop {
      background: rgb(0 0 0 / 0.4);
    }

    header {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.625rem 0.75rem 0.625rem 1rem;
      background: var(--sgc-color-bg--grey);
      border-bottom: 1px solid var(--sgc-color-border);
    }

    h2 {
      flex: 1;
      margin: 0;
      font-size: 1rem;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    header button {
      flex: none;
      display: grid;
      place-items: center;
      width: 1.75rem;
      height: 1.75rem;
      border: none;
      border-radius: 0.25rem;
      background: none;
      line-height: 0;
      cursor: pointer;
      color: var(--sgc-color-text--secondary);
    }

    header button:hover {
      background: var(--sgc-color-bg--white);
      color: var(--sgc-color-text);
    }

    .body {
      overflow-y: auto;
      padding: 0.75rem 1rem;
      min-height: 0;
    }

    sgs-legend-content {
      font-size: 0.8125rem;
    }
  `;

  @consume({ context: catalogServiceContext })
  private catalogService!: CatalogService;

  @property() layerId = '';
  @property() layerLabel?: string;

  private readonly language = new ObservableController(this, languageChanged$);

  // Localized layer title; falls back to the label passed by the opener.
  private readonly titleTask = new Task(this, {
    args: () => [this.layerId, this.language.value ?? currentLanguage()] as const,
    task: async ([id, lang]) => (await this.catalogService.getLayer(id, lang))?.label,
  });

  override firstUpdated(): void {
    this.renderRoot.querySelector('dialog')?.showModal();
  }

  override render() {
    return html`
      <dialog @cancel=${this.onClose} @click=${this.onBackdropClick}>
        <header>
          <h2>${this.titleTask.value ?? this.layerLabel ?? this.layerId}</h2>
          <button
            title=${t('dialog.close')}
            aria-label=${t('dialog.close')}
            @click=${this.onClose}
          >
            ${closeIcon}
          </button>
        </header>
        <div class="body">
          <sgs-legend-content .layerId=${this.layerId}></sgs-legend-content>
        </div>
      </dialog>
    `;
  }

  /** Clicks on the backdrop land on the <dialog> outside its content box. */
  private onBackdropClick(event: MouseEvent): void {
    const dialog = event.target as HTMLElement;
    if (dialog.tagName !== 'DIALOG') {
      return;
    }
    const rect = dialog.getBoundingClientRect();
    const inside =
      event.clientX >= rect.left &&
      event.clientX <= rect.right &&
      event.clientY >= rect.top &&
      event.clientY <= rect.bottom;
    if (!inside) {
      this.onClose();
    }
  }

  private onClose(): void {
    this.dispatchEvent(new CustomEvent('sgs-close', { bubbles: true, composed: true }));
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-layer-info-dialog': SgsLayerInfoDialog;
  }
}
