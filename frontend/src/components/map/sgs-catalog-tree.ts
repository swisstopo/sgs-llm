import { LitElement, css, html, nothing } from 'lit';
import { customElement } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { Task } from '@lit/task';
import { catalogServiceContext, layerServiceContext } from '../../context';
import type { CatalogService } from '../../services/CatalogService';
import type { LayerService } from '../../services/LayerService';
import { ObservableController } from '../../lib/ObservableController';
import { currentLanguage, languageChanged$, t } from '../../i18n/i18n';

/** Browsable curated layer tree (layers/layertree.json5). */
@customElement('sgs-catalog-tree')
export class SgsCatalogTree extends LitElement {
  static override styles = css`
    :host {
      display: block;
      font-size: 0.875rem;
    }

    details {
      border-bottom: 1px solid var(--sgc-color-border, #d5dbe0);
    }

    summary {
      cursor: pointer;
      padding: 0.5rem 0.25rem;
      font-weight: 600;
    }

    ul {
      list-style: none;
      margin: 0;
      padding: 0 0 0.5rem;
    }

    li button {
      display: block;
      width: 100%;
      text-align: left;
      border: none;
      background: none;
      font: inherit;
      font-size: 0.875rem;
      padding: 0.375rem 0.5rem;
      border-radius: 0.25rem;
      cursor: pointer;
    }

    li button:hover:not(:disabled) {
      background: var(--sgc-color-bg--grey, #f0f2f4);
    }

    li button:disabled {
      cursor: default;
      color: var(--sgc-color-text--disabled, #98a6b3);
    }

    .detail {
      font-size: 0.75rem;
      color: var(--sgc-color-text--secondary, #4b5a68);
      margin-left: 0.375rem;
    }

    .status {
      margin: 0.75rem 0 0;
      color: var(--sgc-color-text--secondary, #4b5a68);
    }
  `;

  @consume({ context: catalogServiceContext })
  private catalogService!: CatalogService;

  @consume({ context: layerServiceContext })
  private layerService!: LayerService;

  private readonly language = new ObservableController(this, languageChanged$);

  private readonly treeTask = new Task(this, {
    args: () => [this.language.value ?? currentLanguage()] as const,
    task: ([lang]) => this.catalogService.getTree(lang),
  });

  override connectedCallback(): void {
    super.connectedCallback();
    // Re-render when active layers change so "added" states stay current.
    new ObservableController(this, this.layerService.layers$);
  }

  override render() {
    return this.treeTask.render({
      pending: () => html`<p class="status">${t('catalog.loading')}</p>`,
      error: () => html`<p class="status">${t('catalog.error')}</p>`,
      complete: (groups) => html`
        ${groups.map(
          (group, index) => html`
            <details ?open=${index === 0}>
              <summary>${group.label}</summary>
              <ul>
                ${group.entries.map(
                  (entry) => html`
                    <li>
                      <button
                        ?disabled=${!entry.displayable || this.layerService.isActive(entry.id)}
                        @click=${() => void this.layerService.addOfficialLayer(entry.id)}
                      >
                        ${entry.label}
                        ${!entry.displayable
                          ? html`<span class="detail">${t('search.notDisplayable')}</span>`
                          : this.layerService.isActive(entry.id)
                            ? html`<span class="detail">${t('search.added')}</span>`
                            : nothing}
                      </button>
                    </li>
                  `,
                )}
              </ul>
            </details>
          `,
        )}
      `,
    });
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-catalog-tree': SgsCatalogTree;
  }
}
