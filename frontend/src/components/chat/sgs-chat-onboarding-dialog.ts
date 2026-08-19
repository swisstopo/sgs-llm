import { LitElement, css, html } from 'lit';
import { customElement, query, state } from 'lit/decorators.js';
import { getRuntimeConfig } from '../../config';
import { ObservableController } from '../../lib/ObservableController';
import {
  SUPPORTED_LANGUAGES,
  changeLanguage,
  currentLanguage,
  languageChanged$,
  t,
} from '../../i18n/i18n';
import type { AppLanguage } from '../../i18n/i18n';
import {
  GEODATA_EXPERIENCE_LEVELS,
  INTENDED_USES,
  USER_GROUPS,
  submitOnboarding,
} from '../../onboarding/submitOnboarding';
import type { GeodataExperience, IntendedUse, UserGroup } from '../../onboarding/submitOnboarding';
import { CHAT_ONBOARDING_VERSION } from '../../services/UiService';
import { termsUrl } from '../../terms';

/** Required first-use information shown before the chat panel can open. */
@customElement('sgs-chat-onboarding-dialog')
export class SgsChatOnboardingDialog extends LitElement {
  static override styles = css`
    dialog {
      width: min(32rem, calc(100vw - 2rem));
      max-height: min(85vh, 42rem);
      padding: 0;
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.5rem;
      background: var(--sgc-color-bg--white);
      box-shadow: 0 12px 40px rgb(0 0 0 / 0.3);
      color: var(--sgc-color-text);
    }

    dialog::backdrop {
      background: rgb(0 0 0 / 0.45);
    }

    .layout {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      max-height: min(85vh, 42rem);
    }

    header {
      display: flex;
      align-items: center;
      gap: 1rem;
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--sgc-color-border);
      background: var(--sgc-color-bg--grey);
    }

    h2 {
      flex: 1;
      margin: 0;
      font-size: 1rem;
      line-height: 1.35;
    }

    .language-select {
      flex: none;
      width: auto;
      min-height: 2rem;
      padding: 0.25rem 0.375rem;
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.25rem;
      background: var(--sgc-color-bg--white);
      color: var(--sgc-color-text);
      font: inherit;
      font-size: 0.8125rem;
      font-weight: 600;
      text-transform: uppercase;
    }

    .body {
      min-height: 0;
      overflow-y: auto;
      padding: 1rem;
      font-size: 0.9375rem;
      line-height: 1.5;
    }

    p {
      margin: 0 0 0.875rem;
    }

    ul {
      display: grid;
      gap: 0.625rem;
      margin: 0 0 1rem;
      padding-left: 1.25rem;
    }

    form {
      display: grid;
      gap: 0.875rem;
      margin-top: 1.125rem;
      padding-top: 1rem;
      border-top: 1px solid var(--sgc-color-border--subtle);
    }

    label {
      display: grid;
      gap: 0.375rem;
      font-weight: 600;
    }

    select {
      width: 100%;
      box-sizing: border-box;
      min-height: 2.5rem;
      padding: 0.5rem 0.625rem;
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.25rem;
      background: var(--sgc-color-bg--white);
      color: var(--sgc-color-text);
      font: inherit;
      font-weight: 400;
    }

    a {
      color: var(--sgc-color-brand);
    }

    footer {
      padding: 0.75rem 1rem 1rem;
      border-top: 1px solid var(--sgc-color-border--subtle);
    }

    .accept {
      width: 100%;
      min-height: 2.75rem;
      padding: 0.625rem 1rem;
      border: 1px solid var(--sgc-color-brand);
      border-radius: 0.375rem;
      background: var(--sgc-color-brand);
      color: #ffffff;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
    }

    .accept:hover:not(:disabled) {
      filter: brightness(0.92);
    }

    .accept:disabled {
      opacity: 0.6;
      cursor: default;
    }

    .error {
      margin: 0.625rem 0 0;
      color: var(--sgc-color-brand);
      font-size: 0.875rem;
    }

    button:focus-visible,
    a:focus-visible {
      outline: 2px solid var(--sgc-color-brand);
      outline-offset: 2px;
    }
  `;

  private readonly _language = new ObservableController(this, languageChanged$);

  @state() private submitting = false;
  @state() private submissionFailed = false;
  @state() private selectedUserGroup: UserGroup | '' = '';
  @state() private selectedExperience: GeodataExperience | '' = '';
  @state() private selectedUse: IntendedUse | '' = '';

  @query('#onboarding-user-group') private userGroupSelect!: HTMLSelectElement;
  @query('#onboarding-experience') private experienceSelect!: HTMLSelectElement;
  @query('#onboarding-use') private intendedUseSelect!: HTMLSelectElement;
  @query('form') private formElement!: HTMLFormElement;

  override firstUpdated(): void {
    this.renderRoot.querySelector('dialog')?.showModal();
  }

  override render() {
    return html`
      <dialog
        aria-labelledby="chat-onboarding-title"
        aria-describedby="chat-onboarding-body"
        @cancel=${this.preventDismissal}
      >
        <div class="layout">
          <header>
            <h2 id="chat-onboarding-title">${t('chat.onboarding.title')}</h2>
            <select
              class="language-select"
              aria-label=${t('rail.language')}
              @change=${this.selectLanguage}
            >
              ${SUPPORTED_LANGUAGES.map(
                (language) => html`
                  <option value=${language} ?selected=${language === currentLanguage()}>
                    ${language}
                  </option>
                `,
              )}
            </select>
          </header>
          <div class="body" id="chat-onboarding-body">
            <p>${t('chat.onboarding.introduction')}</p>
            <ul>
              <li>${t('chat.onboarding.personalDataWarning')}</li>
              <li>${t('chat.onboarding.accuracyWarning')}</li>
            </ul>
            <p>
              ${t('chat.onboarding.acknowledgement')}
              <a
                href=${termsUrl(currentLanguage())}
                lang=${currentLanguage()}
                target="_blank"
                rel="noopener noreferrer"
              >
                ${t('chat.onboarding.termsLink')}
              </a>
            </p>
            <form id="chat-onboarding-form" @submit=${this.submit}>
              <label for="onboarding-user-group">
                ${t('chat.onboarding.form.userGroup.label')}
                <select
                  id="onboarding-user-group"
                  required
                  .value=${this.selectedUserGroup}
                  @change=${(event: Event) =>
                    (this.selectedUserGroup = (event.target as HTMLSelectElement)
                      .value as UserGroup)}
                >
                  <option value="" disabled selected>${t('chat.onboarding.form.choose')}</option>
                  ${USER_GROUPS.map(
                    (value) => html`
                      <option value=${value}>
                        ${t(`chat.onboarding.form.userGroup.options.${value}`)}
                      </option>
                    `,
                  )}
                </select>
              </label>
              <label for="onboarding-experience">
                ${t('chat.onboarding.form.experience.label')}
                <select
                  id="onboarding-experience"
                  required
                  .value=${this.selectedExperience}
                  @change=${(event: Event) =>
                    (this.selectedExperience = (event.target as HTMLSelectElement)
                      .value as GeodataExperience)}
                >
                  <option value="" disabled selected>${t('chat.onboarding.form.choose')}</option>
                  ${GEODATA_EXPERIENCE_LEVELS.map(
                    (value) => html`
                      <option value=${value}>
                        ${t(`chat.onboarding.form.experience.options.${value}`)}
                      </option>
                    `,
                  )}
                </select>
              </label>
              <label for="onboarding-use">
                ${t('chat.onboarding.form.intendedUse.label')}
                <select
                  id="onboarding-use"
                  required
                  .value=${this.selectedUse}
                  @change=${(event: Event) =>
                    (this.selectedUse = (event.target as HTMLSelectElement).value as IntendedUse)}
                >
                  <option value="" disabled selected>${t('chat.onboarding.form.choose')}</option>
                  ${INTENDED_USES.map(
                    (value) => html`
                      <option value=${value}>
                        ${t(`chat.onboarding.form.intendedUse.options.${value}`)}
                      </option>
                    `,
                  )}
                </select>
              </label>
            </form>
          </div>
          <footer>
            <button
              class="accept"
              type="submit"
              form="chat-onboarding-form"
              autofocus
              ?disabled=${this.submitting}
            >
              ${this.submitting ? t('chat.onboarding.form.saving') : t('chat.onboarding.accept')}
            </button>
            ${this.submissionFailed
              ? html`<p class="error" role="alert">${t('chat.onboarding.form.saveError')}</p>`
              : null}
          </footer>
        </div>
      </dialog>
    `;
  }

  private preventDismissal(event: Event): void {
    event.preventDefault();
  }

  private selectLanguage(event: Event): void {
    void changeLanguage((event.target as HTMLSelectElement).value as AppLanguage);
  }

  private async submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (this.submitting || !this.formElement.reportValidity()) {
      return;
    }
    this.submitting = true;
    this.submissionFailed = false;
    try {
      await submitOnboarding(getRuntimeConfig().feedbackUrl, {
        type: 'onboarding',
        user_group: this.userGroupSelect.value as UserGroup,
        geodata_experience: this.experienceSelect.value as GeodataExperience,
        intended_use: this.intendedUseSelect.value as IntendedUse,
        consent_version: CHAT_ONBOARDING_VERSION,
        lang: document.documentElement.lang || 'de',
      });
      this.dispatchEvent(new CustomEvent('sgs-accept', { bubbles: true, composed: true }));
    } catch (error) {
      console.error('onboarding submission failed', error);
      this.submissionFailed = true;
    } finally {
      this.submitting = false;
    }
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-chat-onboarding-dialog': SgsChatOnboardingDialog;
  }
}
