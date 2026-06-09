import { LitElement, css, html } from 'lit';
import { customElement, property, query } from 'lit/decorators.js';
import { ObservableController } from '../../lib/ObservableController';
import { languageChanged$, t } from '../../i18n/i18n';

/**
 * Message input. Emits `sgs-send` with the text, or `sgs-cancel` while an
 * exchange is streaming. Enter sends, Shift+Enter inserts a newline.
 */
@customElement('sgs-composer')
export class SgsComposer extends LitElement {
  static override styles = css`
    :host {
      display: flex;
      gap: 0.5rem;
      align-items: flex-end;
    }

    textarea {
      flex: 1;
      resize: none;
      font: inherit;
      font-size: 0.875rem;
      padding: 0.5rem 0.625rem;
      border: 1px solid var(--sgc-color-border, #d5dbe0);
      border-radius: 0.375rem;
      min-height: 2.5rem;
      max-height: 8rem;
      box-sizing: border-box;
      background: var(--sgc-color-bg--white, #ffffff);
    }

    textarea:focus {
      outline: 2px solid var(--sgc-color-brand, #d8232a);
      outline-offset: -1px;
    }

    button {
      font: inherit;
      font-size: 0.875rem;
      padding: 0.5rem 0.875rem;
      border-radius: 0.375rem;
      border: 1px solid var(--sgc-color-brand, #d8232a);
      background: var(--sgc-color-brand, #d8232a);
      color: #fff;
      cursor: pointer;
      min-height: 2.5rem;
    }

    button.cancel {
      background: var(--sgc-color-bg--white, #ffffff);
      color: var(--sgc-color-brand, #d8232a);
    }

    button:disabled {
      opacity: 0.5;
      cursor: default;
    }
  `;

  @property({ type: Boolean }) busy = false;
  @property({ type: Boolean }) disabled = false;

  @query('textarea') private textarea!: HTMLTextAreaElement;

  private readonly _language = new ObservableController(this, languageChanged$);

  override render() {
    return html`
      <textarea
        rows="1"
        placeholder=${t('chat.placeholder')}
        ?disabled=${this.disabled}
        @keydown=${this.onKeydown}
        @input=${this.autosize}
      ></textarea>
      ${this.busy
        ? html`<button class="cancel" @click=${this.cancel}>${t('chat.cancel')}</button>`
        : html`<button ?disabled=${this.disabled} @click=${this.send}>${t('chat.send')}</button>`}
    `;
  }

  private onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.send();
    }
  }

  private autosize(): void {
    this.textarea.style.height = 'auto';
    this.textarea.style.height = `${this.textarea.scrollHeight}px`;
  }

  private send(): void {
    const content = this.textarea.value.trim();
    if (content.length === 0 || this.busy || this.disabled) {
      return;
    }
    this.dispatchEvent(new CustomEvent('sgs-send', { detail: { content } }));
    this.textarea.value = '';
    this.autosize();
  }

  private cancel(): void {
    this.dispatchEvent(new CustomEvent('sgs-cancel'));
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-composer': SgsComposer;
  }
}
