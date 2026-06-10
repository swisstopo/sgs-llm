import { LitElement, css, html } from 'lit';
import { customElement } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { mapServiceContext } from '../../context';
import type { MapService } from '../../services/MapService';
import { ObservableController } from '../../lib/ObservableController';
import { languageChanged$, t } from '../../i18n/i18n';
import { zoomInIcon, zoomOutIcon } from '../shell/icons';

/** Horizontal zoom-out/zoom-in bar, SwissGeo-style (bottom-right cluster). */
@customElement('sgs-zoom-controls')
export class SgsZoomControls extends LitElement {
  static override styles = css`
    :host {
      display: flex;
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.375rem;
      background: var(--sgc-color-bg--white);
      box-shadow: 0 2px 10px rgb(0 0 0 / 0.25);
      overflow: hidden;
    }

    button {
      display: grid;
      place-items: center;
      width: 2.75rem;
      height: 2.75rem;
      border: none;
      background: none;
      line-height: 0;
      cursor: pointer;
      color: var(--sgc-color-text);
    }

    button:hover {
      background: var(--sgc-color-bg--grey);
      color: var(--sgc-color-brand);
    }

    button + button {
      border-left: 1px solid var(--sgc-color-border--subtle);
    }
  `;

  @consume({ context: mapServiceContext })
  private mapService!: MapService;

  private readonly _language = new ObservableController(this, languageChanged$);

  override render() {
    return html`
      <button
        title=${t('map.zoomOut')}
        aria-label=${t('map.zoomOut')}
        @click=${() => this.mapService.zoomBy(-1)}
      >
        ${zoomOutIcon}
      </button>
      <button
        title=${t('map.zoomIn')}
        aria-label=${t('map.zoomIn')}
        @click=${() => this.mapService.zoomBy(1)}
      >
        ${zoomInIcon}
      </button>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-zoom-controls': SgsZoomControls;
  }
}
