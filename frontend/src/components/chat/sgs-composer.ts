import { LitElement, css, html, nothing, svg } from 'lit';
import { customElement, property, query, state } from 'lit/decorators.js';
import { ObservableController } from '../../lib/ObservableController';
import { languageChanged$, t } from '../../i18n/i18n';
import { isApertusAvailable } from '../../models/apertusAvailability';
import type { ModelPreference } from '../../protocol/v1';
import { checkIcon, chevronDownIcon, infoIcon } from '../shell/icons';

const MODEL_OPTIONS: readonly ModelPreference[] = ['primary', 'secondary', 'apertus'];

/** Message input and explicit model picker. */
@customElement('sgs-composer')
export class SgsComposer extends LitElement {
  static override styles = css`
    :host {
      display: grid;
      gap: 0.5rem;
    }

    .model-control {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      min-width: 0;
    }

    .model-label {
      flex: none;
      color: var(--sgc-color-text--secondary);
      font-size: 0.75rem;
      font-weight: 600;
    }

    .model-picker {
      position: relative;
      flex: 1;
      min-width: 0;
      width: auto;
    }

    .model-trigger,
    .model-option {
      display: grid;
      grid-template-columns: 1.25rem minmax(0, 1fr) auto;
      align-items: center;
      gap: 0.5rem;
      width: 100%;
      border: 0;
      background: transparent;
      color: var(--sgc-color-text);
      font: inherit;
      text-align: left;
      cursor: pointer;
    }

    .model-trigger {
      min-height: 2rem;
      padding: 0.3125rem 0.5rem;
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.375rem;
      background: var(--sgc-color-bg--white);
      font-size: 0.75rem;
    }

    .model-trigger:hover:not(:disabled) {
      border-color: var(--sgc-color-text--secondary);
    }

    .model-trigger:focus-visible,
    .model-option:focus-visible {
      outline: 2px solid var(--sgc-color-brand);
      outline-offset: 1px;
    }

    .model-trigger:disabled {
      color: var(--sgc-color-text--disabled);
      cursor: default;
    }

    .model-trigger .chevron {
      display: grid;
      color: var(--sgc-color-text--secondary);
      transition: transform var(--sgs-motion-duration--fast) var(--sgs-motion-ease);
    }

    .model-trigger[aria-expanded='true'] .chevron {
      transform: rotate(180deg);
    }

    .model-menu {
      position: absolute;
      z-index: 30;
      bottom: calc(100% + 0.375rem);
      left: 0;
      box-sizing: border-box;
      width: 100%;
      padding: 0.25rem;
      border: 0;
      border-radius: 0.5rem;
      background: var(--sgc-color-bg--white);
      box-shadow: 0 0.375rem 1rem rgb(28 40 52 / 16%);
    }

    .model-option {
      min-height: 2.5rem;
      padding: 0.4375rem 0.5rem;
      border-radius: 0.375rem;
      font-size: 0.8125rem;
    }

    .model-option[data-model='apertus'] {
      min-height: 3.5rem;
      padding-block: 0.625rem;
    }

    .model-option:not([aria-disabled='true']):hover,
    .model-option[aria-selected='true'] {
      background: var(--sgc-color-bg--grey);
    }

    .model-option-wrap {
      position: relative;
    }

    .model-option-wrap:hover,
    .model-option-wrap:focus-within {
      z-index: 4;
    }

    .model-option[aria-disabled='true'] {
      color: var(--sgc-color-text--disabled);
      cursor: not-allowed;
    }

    .model-option[aria-disabled='true'] .model-logo {
      opacity: 0.48;
    }

    .model-copy {
      display: grid;
      gap: 0.125rem;
      min-width: 0;
    }

    .model-meta {
      color: var(--sgc-color-text--secondary);
      font-size: 0.6875rem;
      line-height: 1.35;
      white-space: normal;
    }

    .model-option[aria-disabled='true'] .model-meta {
      color: var(--sgc-color-text--disabled);
    }

    .model-tooltip {
      position: absolute;
      z-index: 3;
      right: 0;
      bottom: calc(100% + 0.375rem);
      box-sizing: border-box;
      width: min(18rem, calc(100vw - 2rem));
      padding: 0.5rem 0.625rem;
      border-radius: 0.375rem;
      background: #1c2834;
      box-shadow: 0 0.375rem 1rem rgb(28 40 52 / 28%);
      color: #fff;
      font-size: 0.75rem;
      line-height: 1.4;
      opacity: 0;
      pointer-events: none;
      transform: translateY(0.25rem);
      transition:
        opacity var(--sgs-motion-duration--fast) var(--sgs-motion-ease),
        transform var(--sgs-motion-duration--fast) var(--sgs-motion-ease);
      visibility: hidden;
    }

    .model-option-wrap:hover .model-tooltip,
    .model-option-wrap:focus-within .model-tooltip {
      opacity: 1;
      transform: translateY(0);
      visibility: visible;
    }

    .model-option .selected {
      display: grid;
      color: var(--sgc-color-brand);
    }

    .model-logo {
      display: grid;
      place-items: center;
      width: 1.25rem;
      height: 1.25rem;
    }

    .model-logo svg {
      width: 1.125rem;
      height: 1.125rem;
    }

    .model-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .model-availability {
      display: flex;
      gap: 0.375rem;
      align-items: flex-start;
      margin: 0;
      color: var(--sgc-color-text--secondary);
      font-size: 0.75rem;
      line-height: 1.4;
    }

    .model-availability svg {
      flex: none;
      width: 1rem;
      height: 1rem;
      margin-top: 0.0625rem;
    }

    .input-row {
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
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.375rem;
      min-height: 2.5rem;
      max-height: 8rem;
      box-sizing: border-box;
      background: var(--sgc-color-bg--white);
    }

    textarea:focus {
      outline: 2px solid var(--sgc-color-brand);
      outline-offset: -1px;
    }

    .submit {
      min-height: 2.5rem;
      padding: 0.5rem 0.875rem;
      border: 1px solid var(--sgc-color-brand);
      border-radius: 0.375rem;
      background: var(--sgc-color-brand);
      color: #fff;
      font: inherit;
      font-size: 0.875rem;
      cursor: pointer;
    }

    .submit.cancel {
      background: var(--sgc-color-bg--white);
      color: var(--sgc-color-brand);
    }

    .submit:disabled {
      opacity: 0.5;
      cursor: default;
    }
  `;

  @property({ type: Boolean }) busy = false;
  @property({ type: Boolean }) disabled = false;
  @property() model: ModelPreference = 'primary';

  @state() private modelMenuOpen = false;
  @state() private availabilityClock = Date.now();

  @query('textarea') private textarea!: HTMLTextAreaElement;
  @query('.model-trigger') private modelTrigger!: HTMLButtonElement;

  private readonly _language = new ObservableController(this, languageChanged$);
  private availabilityTimer?: number;

  private readonly onDocumentPointerDown = (event: PointerEvent): void => {
    if (this.modelMenuOpen && !event.composedPath().includes(this)) {
      this.modelMenuOpen = false;
    }
  };

  override connectedCallback(): void {
    super.connectedCallback();
    document.addEventListener('pointerdown', this.onDocumentPointerDown);
    this.availabilityClock = Date.now();
    this.availabilityTimer = window.setInterval(() => {
      this.availabilityClock = Date.now();
    }, 30_000);
  }

  override disconnectedCallback(): void {
    document.removeEventListener('pointerdown', this.onDocumentPointerDown);
    if (this.availabilityTimer !== undefined) {
      window.clearInterval(this.availabilityTimer);
      this.availabilityTimer = undefined;
    }
    super.disconnectedCallback();
  }

  override render() {
    const modelDisabled = this.busy || this.disabled;
    const selectedModelUnavailable = !this.modelAvailable(this.model);
    return html`
      <div class="model-control" @keydown=${this.onModelKeydown}>
        <span class="model-label" id="model-label">${t('chat.model.label')}</span>
        <div class="model-picker">
          <button
            class="model-trigger"
            type="button"
            aria-haspopup="listbox"
            aria-expanded=${this.modelMenuOpen && !modelDisabled ? 'true' : 'false'}
            aria-labelledby="model-label selected-model-name"
            aria-describedby=${selectedModelUnavailable ? 'selected-model-availability' : nothing}
            ?disabled=${modelDisabled}
            @click=${this.toggleModelMenu}
          >
            ${this.renderModelLogo(this.model)}
            <span class="model-name" id="selected-model-name">${this.modelName(this.model)}</span>
            <span class="chevron">${chevronDownIcon}</span>
          </button>
          ${this.modelMenuOpen && !modelDisabled
            ? html`
                <div class="model-menu" role="listbox" aria-labelledby="model-label">
                  ${MODEL_OPTIONS.map((model) => this.renderModelOption(model))}
                </div>
              `
            : nothing}
        </div>
      </div>
      ${selectedModelUnavailable
        ? html`
            <p class="model-availability" id="selected-model-availability" role="status">
              ${infoIcon}<span>${t('chat.model.apertusUnavailable')}</span>
            </p>
          `
        : nothing}
      <div class="input-row">
        <textarea
          rows="1"
          placeholder=${t('chat.placeholder')}
          ?disabled=${this.disabled}
          @keydown=${this.onComposerKeydown}
          @input=${this.autosize}
        ></textarea>
        ${this.busy
          ? html`<button class="submit cancel" @click=${this.cancel}>${t('chat.cancel')}</button>`
          : html`<button
              class="submit"
              ?disabled=${this.disabled || selectedModelUnavailable}
              @click=${this.send}
            >
              ${t('chat.send')}
            </button>`}
      </div>
    `;
  }

  private renderModelOption(model: ModelPreference) {
    const selected = this.model === model;
    const available = this.modelAvailable(model);
    const tooltipId =
      model === 'apertus' && !available ? 'apertus-availability-tooltip' : undefined;
    return html`
      <div class="model-option-wrap">
        <button
          class="model-option"
          type="button"
          role="option"
          aria-selected=${selected ? 'true' : 'false'}
          aria-disabled=${available ? 'false' : 'true'}
          aria-describedby=${tooltipId ?? nothing}
          title=${model === 'apertus' && !available ? t('chat.model.apertusUnavailable') : nothing}
          data-model=${model}
          @click=${() => this.selectModel(model)}
        >
          ${this.renderModelLogo(model)}
          <span class="model-copy">
            <span class="model-name">${this.modelName(model)}</span>
            ${model === 'apertus'
              ? html`<span class="model-meta">${t('chat.model.apertusSchedule')}</span>`
              : nothing}
          </span>
          <span class="selected">${available ? (selected ? checkIcon : nothing) : infoIcon}</span>
        </button>
        ${tooltipId
          ? html`<span class="model-tooltip" id=${tooltipId} role="tooltip">
              ${t('chat.model.apertusUnavailable')}
            </span>`
          : nothing}
      </div>
    `;
  }

  private renderModelLogo(model: ModelPreference) {
    let body;
    let color;
    if (model === 'primary') {
      body = svg`<path d="m4.7144 15.9555 4.7174-2.6471.079-.2307-.079-.1275h-.2307l-.7893-.0486-2.6956-.0729-2.3375-.0971-2.2646-.1214-.5707-.1215-.5343-.7042.0546-.3522.4797-.3218.686.0608 1.5179.1032 2.2767.1578 1.6514.0972 2.4468.255h.3886l.0546-.1579-.1336-.0971-.1032-.0972L6.973 9.8356l-2.55-1.6879-1.3356-.9714-.7225-.4918-.3643-.4614-.1578-1.0078.6557-.7225.8803.0607.2246.0607.8925.686 1.9064 1.4754 2.4893 1.8336.3643.3035.1457-.1032.0182-.0728-.164-.2733-1.3539-2.4467-1.445-2.4893-.6435-1.032-.17-.6194c-.0607-.255-.1032-.4674-.1032-.7285L6.287.1335 6.6997 0l.9957.1336.419.3642.6192 1.4147 1.0018 2.2282 1.5543 3.0296.4553.8985.2429.8318.091.255h.1579v-.1457l.1275-1.706.2368-2.0947.2307-2.6957.0789-.7589.3764-.9107.7468-.4918.5828.2793.4797.686-.0668.4433-.2853 1.8517-.5586 2.9021-.3643 1.9429h.2125l.2429-.2429.9835-1.3053 1.6514-2.0643.7286-.8196.85-.9046.5464-.4311h1.0321l.759 1.1293-.34 1.1657-1.0625 1.3478-.8804 1.1414-1.2628 1.7-.7893 1.36.0729.1093.1882-.0183 2.8535-.607 1.5421-.2794 1.8396-.3157.8318.3886.091.3946-.3278.8075-1.967.4857-2.3072.4614-3.4364.8136-.0425.0304.0486.0607 1.5482.1457.6618.0364h1.621l3.0175.2247.7892.522.4736.6376-.079.4857-1.2142.6193-1.6393-.3886-3.825-.9107-1.3113-.3279h-.1822v.1093l1.0929 1.0686 2.0035 1.8092 2.5075 2.3314.1275.5768-.3218.4554-.34-.0486-2.2039-1.6575-.85-.7468-1.9246-1.621h-.1275v.17l.4432.6496 2.3436 3.5214.1214 1.0807-.17.3521-.6071.2125-.6679-.1214-1.3721-1.9246L14.38 17.959l-1.1414-1.9428-.1397.079-.674 7.2552-.3156.3703-.7286.2793-.6071-.4614-.3218-.7468.3218-1.4753.3886-1.9246.3157-1.53.2853-1.9004.17-.6314-.0121-.0425-.1397.0182-1.4328 1.9672-2.1796 2.9446-1.7243 1.8456-.4128.164-.7164-.3704.0667-.6618.4008-.5889 2.386-3.0357 1.4389-1.882.929-1.0868-.0062-.1579h-.0546l-6.3385 4.1164-1.1293.1457-.4857-.4554.0608-.7467.2307-.2429 1.9064-1.3114Z" />`;
      color = '#D97757';
    } else if (model === 'secondary') {
      body = svg`<path d="M17.143 3.429v3.428h-3.429v3.429h-3.428V6.857H6.857V3.43H3.43v13.714H0v3.428h10.286v-3.428H6.857v-3.429h3.429v3.429h3.429v-3.429h3.428v3.429h-3.428v3.428H24v-3.428h-3.43V3.429z" />`;
      color = '#FA520F';
    } else {
      body = svg`<path d="M12 2 22 22h-4.4l-2-4.25H8.4L6.4 22H2L12 2Zm0 7.1-2.15 4.65h4.3L12 9.1Z" />`;
      color = '#DC0018';
    }
    return html`<span class="model-logo" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill=${color} xmlns="http://www.w3.org/2000/svg">${body}</svg>
    </span>`;
  }

  private modelName(model: ModelPreference): string {
    if (model === 'primary') {
      return t('chat.model.primary');
    }
    if (model === 'secondary') {
      return t('chat.model.secondary');
    }
    return t('chat.model.apertus');
  }

  private modelAvailable(model: ModelPreference): boolean {
    return model !== 'apertus' || isApertusAvailable(new Date(this.availabilityClock));
  }

  private toggleModelMenu(): void {
    if (!this.busy && !this.disabled) {
      this.modelMenuOpen = !this.modelMenuOpen;
    }
  }

  private selectModel(model: ModelPreference): void {
    if (!this.modelAvailable(model)) {
      return;
    }
    this.model = model;
    this.modelMenuOpen = false;
    this.dispatchEvent(new CustomEvent('sgs-model-change', { detail: { model } }));
    this.modelTrigger.focus();
  }

  private onModelKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape' && this.modelMenuOpen) {
      event.preventDefault();
      this.modelMenuOpen = false;
      this.modelTrigger.focus();
      return;
    }
    if (!this.modelMenuOpen || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      return;
    }
    const options = [...this.renderRoot.querySelectorAll<HTMLButtonElement>('.model-option')];
    if (options.length === 0) {
      return;
    }
    event.preventDefault();
    const current = options.indexOf(this.renderRoot.querySelector(':focus') as HTMLButtonElement);
    let index = event.key === 'ArrowUp' || event.key === 'End' ? options.length - 1 : 0;
    if (current >= 0 && event.key === 'ArrowDown') {
      index = (current + 1) % options.length;
    } else if (current >= 0 && event.key === 'ArrowUp') {
      index = (current - 1 + options.length) % options.length;
    }
    options[index]?.focus();
  }

  private onComposerKeydown(event: KeyboardEvent): void {
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
    if (content.length === 0 || this.busy || this.disabled || !this.modelAvailable(this.model)) {
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
