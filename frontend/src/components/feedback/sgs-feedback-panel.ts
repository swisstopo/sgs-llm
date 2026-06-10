import { LitElement, css, html, nothing } from 'lit';
import { customElement, query, state } from 'lit/decorators.js';
import { getRuntimeConfig } from '../../config';
import { FEEDBACK_CATEGORIES, submitFeedback } from '../../feedback/submitFeedback';
import type { FeedbackCategory } from '../../feedback/submitFeedback';
import { ObservableController } from '../../lib/ObservableController';
import { currentLanguage, languageChanged$, t } from '../../i18n/i18n';

type FormState = 'idle' | 'sending' | 'success' | 'error';

/** Feedback form panel (category, message, optional email). */
@customElement('sgs-feedback-panel')
export class SgsFeedbackPanel extends LitElement {
  static override styles = css`
    :host {
      display: block;
      padding: 1rem;
      overflow-y: auto;
      min-height: 0;
      font-size: 0.875rem;
    }

    label {
      display: block;
      font-weight: 600;
      margin: 0.875rem 0 0.25rem;
    }

    label:first-of-type {
      margin-top: 0;
    }

    .hint {
      font-weight: 400;
      color: var(--sgc-color-text--secondary, #4b5a68);
    }

    select,
    textarea,
    input {
      width: 100%;
      box-sizing: border-box;
      font: inherit;
      padding: 0.5rem 0.625rem;
      border: 1px solid var(--sgc-color-border, #d5dbe0);
      border-radius: 0.25rem;
      background: var(--sgc-color-bg--white, #ffffff);
    }

    select:focus,
    textarea:focus,
    input:focus {
      outline: 2px solid var(--sgc-color-brand, #d8232a);
      outline-offset: -1px;
    }

    textarea {
      min-height: 9rem;
      resize: vertical;
    }

    .actions {
      margin-top: 1rem;
    }

    button.submit {
      font: inherit;
      padding: 0.5rem 1rem;
      border-radius: 0.375rem;
      border: 1px solid var(--sgc-color-brand, #d8232a);
      background: var(--sgc-color-brand, #d8232a);
      color: #fff;
      cursor: pointer;
    }

    button.submit:disabled {
      opacity: 0.6;
      cursor: default;
    }

    .error-note {
      color: var(--sgc-color-brand, #d8232a);
      margin: 0.5rem 0 0;
    }

    .success {
      display: grid;
      gap: 0.5rem;
      padding: 1.5rem 0;
      text-align: center;
      color: var(--sgc-color-text, #1c2834);
    }

    .success .check {
      font-size: 2rem;
      color: #2e7d32;
    }
  `;

  @state() private formState: FormState = 'idle';
  @state() private validationError = false;

  @query('select') private categorySelect!: HTMLSelectElement;
  @query('textarea') private messageArea!: HTMLTextAreaElement;
  @query('input[type=email]') private emailInput!: HTMLInputElement;

  private readonly _language = new ObservableController(this, languageChanged$);

  override render() {
    if (this.formState === 'success') {
      return html`
        <div class="success">
          <span class="check">✓</span>
          <p>${t('feedback.success')}</p>
        </div>
      `;
    }
    return html`
      <label for="fb-category">${t('feedback.category')}</label>
      <select id="fb-category">
        ${FEEDBACK_CATEGORIES.map(
          (category) =>
            html`<option value=${category}>${t(`feedback.categories.${category}`)}</option>`,
        )}
      </select>

      <label for="fb-message">${t('feedback.message')}</label>
      <textarea
        id="fb-message"
        placeholder=${t('feedback.messagePlaceholder')}
        @input=${() => (this.validationError = false)}
      ></textarea>
      ${this.validationError
        ? html`<p class="error-note">${t('feedback.messageRequired')}</p>`
        : nothing}

      <label for="fb-email">
        ${t('feedback.email')} <span class="hint">(${t('feedback.emailHint')})</span>
      </label>
      <input id="fb-email" type="email" autocomplete="email" />

      <div class="actions">
        <button
          class="submit"
          ?disabled=${this.formState === 'sending'}
          @click=${() => void this.submit()}
        >
          ${this.formState === 'sending' ? t('feedback.sending') : t('feedback.submit')}
        </button>
      </div>
      ${this.formState === 'error'
        ? html`<p class="error-note">${t('feedback.error')}</p>`
        : nothing}
    `;
  }

  private async submit(): Promise<void> {
    const message = this.messageArea.value.trim();
    if (message.length === 0) {
      this.validationError = true;
      return;
    }
    this.formState = 'sending';
    try {
      const email = this.emailInput.value.trim();
      await submitFeedback(getRuntimeConfig().feedbackUrl, {
        category: this.categorySelect.value as FeedbackCategory,
        message,
        email: email.length > 0 ? email : undefined,
        lang: currentLanguage(),
      });
      this.formState = 'success';
    } catch (error) {
      console.error('feedback submission failed', error);
      this.formState = 'error';
    }
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-feedback-panel': SgsFeedbackPanel;
  }
}
