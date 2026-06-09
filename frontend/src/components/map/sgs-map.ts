import { LitElement, html } from 'lit';
import { customElement } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { mapServiceContext } from '../../context';
import type { MapService } from '../../services/MapService';
import './sgs-basemap-switcher';
import './sgs-layer-panel';

/**
 * Hosts the OpenLayers map. Renders in light DOM because `ol/ol.css`
 * (controls, attribution, overlays) is a document-level stylesheet that
 * cannot style inside a shadow root.
 */
@customElement('sgs-map')
export class SgsMap extends LitElement {
  @consume({ context: mapServiceContext })
  private mapService!: MapService;

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  override render() {
    return html`
      <div class="sgs-map-target"></div>
      <sgs-basemap-switcher></sgs-basemap-switcher>
      <sgs-layer-panel></sgs-layer-panel>
    `;
  }

  protected override firstUpdated(): void {
    const target = this.querySelector<HTMLElement>('.sgs-map-target');
    if (target) {
      this.mapService.attach(target);
    }
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.mapService.detach();
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-map': SgsMap;
  }
}
