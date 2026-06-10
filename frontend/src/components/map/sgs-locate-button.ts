import { LitElement, css, html, nothing } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { mapServiceContext } from '../../context';
import type { MapService } from '../../services/MapService';
import { lonLatToLV95InBounds } from '../../lib/projection';
import { ObservableController } from '../../lib/ObservableController';
import { languageChanged$, t } from '../../i18n/i18n';
import { locateIcon } from '../shell/icons';

/** Resolution after locating, in m/px (LV95 zoom level 19). */
const LOCATE_RESOLUTION = 20;

type LocateNotice = 'outside' | 'denied' | 'unavailable';

/**
 * "Locate me" map control: centers the map on the browser's geolocation and
 * marks it with a dot. A second click removes the marker. Errors and
 * out-of-Switzerland positions show a short-lived notice bubble.
 */
@customElement('sgs-locate-button')
export class SgsLocateButton extends LitElement {
  static override styles = css`
    :host {
      position: relative;
      display: block;
    }

    button {
      display: grid;
      place-items: center;
      width: 2.75rem;
      height: 2.75rem;
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.375rem;
      background: var(--sgc-color-bg--white);
      box-shadow: 0 2px 10px rgb(0 0 0 / 0.25);
      cursor: pointer;
      color: var(--sgc-color-text);
      line-height: 0;
    }

    button:hover {
      color: var(--sgc-color-brand);
    }

    button[data-active] {
      color: var(--sgc-color-brand);
      border-color: var(--sgc-color-brand);
    }

    button:disabled {
      color: var(--sgc-color-text--disabled);
      cursor: default;
    }

    .notice {
      position: absolute;
      right: calc(100% + 0.5rem);
      top: 50%;
      transform: translateY(-50%);
      white-space: nowrap;
      background: var(--sgc-color-bg--white);
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.375rem;
      box-shadow: 0 2px 10px rgb(0 0 0 / 0.25);
      padding: 0.375rem 0.625rem;
      font-size: 0.75rem;
      color: var(--sgc-color-text);
    }
  `;

  @consume({ context: mapServiceContext })
  private mapService!: MapService;

  @state() private active = false;
  @state() private busy = false;
  @state() private notice?: LocateNotice;

  private noticeHandle?: ReturnType<typeof setTimeout>;

  private readonly _language = new ObservableController(this, languageChanged$);

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    clearTimeout(this.noticeHandle);
  }

  override render() {
    const label = this.active ? t('locate.hide') : t('locate.show');
    return html`
      ${this.notice
        ? html`<span class="notice" role="status">${t(`locate.${this.notice}`)}</span>`
        : nothing}
      <button
        title=${label}
        aria-label=${label}
        aria-pressed=${this.active}
        ?disabled=${this.busy}
        ?data-active=${this.active}
        @click=${this.onClick}
      >
        ${locateIcon}
      </button>
    `;
  }

  private onClick(): void {
    if (this.active) {
      this.mapService.clearLocationMarker();
      this.active = false;
      return;
    }
    if (!('geolocation' in navigator)) {
      this.showNotice('unavailable');
      return;
    }
    this.busy = true;
    navigator.geolocation.getCurrentPosition(
      (position) => {
        this.busy = false;
        const coordinate = lonLatToLV95InBounds([
          position.coords.longitude,
          position.coords.latitude,
        ]);
        if (!coordinate) {
          this.showNotice('outside');
          return;
        }
        this.mapService.setLocationMarker(coordinate);
        this.mapService.animateTo(coordinate, LOCATE_RESOLUTION);
        this.active = true;
      },
      (error) => {
        this.busy = false;
        this.showNotice(error.code === error.PERMISSION_DENIED ? 'denied' : 'unavailable');
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
    );
  }

  private showNotice(notice: LocateNotice): void {
    clearTimeout(this.noticeHandle);
    this.notice = notice;
    this.noticeHandle = setTimeout(() => (this.notice = undefined), 4000);
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-locate-button': SgsLocateButton;
  }
}
