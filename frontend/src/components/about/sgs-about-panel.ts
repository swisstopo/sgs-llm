import { LitElement, css, html } from 'lit';
import { customElement } from 'lit/decorators.js';
import { ObservableController } from '../../lib/ObservableController';
import { languageChanged$, t } from '../../i18n/i18n';

const REPO_URL = 'https://github.com/swisstopo/sgs-llm';
const GEOADMIN_API_URL = 'https://api3.geo.admin.ch';
const AGEOSPATIAL_URL = 'https://www.ageospatial.com';
const ASKEARTH_URL = 'https://ask.earth';

/** "About the project" panel: description, partners, sources, disclaimer. */
@customElement('sgs-about-panel')
export class SgsAboutPanel extends LitElement {
  static override styles = css`
    :host {
      display: block;
      padding: 1rem;
      overflow-y: auto;
      min-height: 0;
      font-size: 0.875rem;
      line-height: 1.55;
    }

    p {
      margin: 0 0 0.75rem;
    }

    h3 {
      margin: 1.25rem 0 0.375rem;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--sgc-color-text--secondary, #4b5a68);
    }

    ul {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 0.375rem;
    }

    a {
      color: var(--sgc-color-brand, #d8232a);
      text-decoration: none;
    }

    a:hover {
      text-decoration: underline;
    }

    .role {
      display: block;
      font-size: 0.8125rem;
      color: var(--sgc-color-text--secondary, #4b5a68);
    }

    .disclaimer {
      margin-top: 1.25rem;
      padding-top: 0.875rem;
      border-top: 1px solid var(--sgc-color-border, #d5dbe0);
      font-size: 0.8125rem;
      color: var(--sgc-color-text--secondary, #4b5a68);
    }
  `;

  private readonly _language = new ObservableController(this, languageChanged$);

  override render() {
    return html`
      <p>${t('about.description')}</p>

      <h3>${t('about.builtByTitle')}</h3>
      <ul>
        <li>
          <a href=${AGEOSPATIAL_URL} target="_blank" rel="noopener noreferrer">Ageospatial Sàrl</a>
          <span class="role">${t('about.builtBy.ageospatial')}</span>
        </li>
        <li>
          <a href=${ASKEARTH_URL} target="_blank" rel="noopener noreferrer">askEarth AG</a>
          <span class="role">${t('about.builtBy.askearth')}</span>
        </li>
      </ul>
      <p class="role" style="margin-top: 0.5rem;">${t('about.builtBy.for')}</p>

      <h3>${t('about.dataSourcesTitle')}</h3>
      <ul>
        <li>
          <a href=${GEOADMIN_API_URL} target="_blank" rel="noopener noreferrer">
            api3.geo.admin.ch
          </a>
          <span class="role">${t('about.dataSources.geoadmin')}</span>
        </li>
      </ul>

      <h3>${t('about.projectTitle')}</h3>
      <ul>
        <li>
          <a href=${REPO_URL} target="_blank" rel="noopener noreferrer">${t('about.github')}</a>
          <span class="role">${t('about.license')}</span>
        </li>
      </ul>

      <p class="disclaimer">${t('about.disclaimer')}</p>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-about-panel': SgsAboutPanel;
  }
}
