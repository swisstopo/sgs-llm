import { LitElement, css, html } from 'lit';
import { customElement } from 'lit/decorators.js';

const MIN_WIDTH_PX = 320;

/**
 * Drag handle between the chat column and the map. Writes `--chat-width`
 * on the app shell.
 */
@customElement('sgs-split-handle')
export class SgsSplitHandle extends LitElement {
  static override styles = css`
    :host {
      display: block;
      width: 6px;
      cursor: col-resize;
      background: transparent;
      transition: background 0.15s;
    }

    :host(:hover),
    :host([data-dragging]) {
      background: var(--sgc-color-brand, #d8232a);
    }
  `;

  override render() {
    return html``;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this.addEventListener('pointerdown', this.onPointerDown);
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.removeEventListener('pointerdown', this.onPointerDown);
  }

  private readonly onPointerDown = (down: PointerEvent): void => {
    down.preventDefault();
    this.setPointerCapture(down.pointerId);
    this.toggleAttribute('data-dragging', true);
    const shell = this.closest('sgs-app');

    const onMove = (move: PointerEvent): void => {
      const max = window.innerWidth * 0.6;
      const width = Math.min(Math.max(move.clientX, MIN_WIDTH_PX), max);
      (shell as HTMLElement | null)?.style.setProperty('--chat-width', `${width}px`);
    };
    const onUp = (): void => {
      this.toggleAttribute('data-dragging', false);
      this.removeEventListener('pointermove', onMove);
      this.removeEventListener('pointerup', onUp);
    };
    this.addEventListener('pointermove', onMove);
    this.addEventListener('pointerup', onUp);
  };
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-split-handle': SgsSplitHandle;
  }
}
