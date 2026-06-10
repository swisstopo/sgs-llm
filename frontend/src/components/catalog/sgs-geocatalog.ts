import { LitElement, css, html, nothing } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { Task } from '@lit/task';
import { catalogServiceContext, layerServiceContext } from '../../context';
import type { CatalogService } from '../../services/CatalogService';
import type { AddLayerResult, LayerService } from '../../services/LayerService';
import { filterCatalogTree } from '../../swisstopo/catalogApi';
import type { CatalogFolderNode, CatalogLayerNode, CatalogNode } from '../../swisstopo/catalogApi';
import { ObservableController } from '../../lib/ObservableController';
import { currentLanguage, languageChanged$, t } from '../../i18n/i18n';

const DEFAULT_TOPIC = 'ech';

/**
 * Geocatalog panel: official Swisstopo catalog tree per topic
 * (CatalogServer), with an in-tree filter and add-to-map buttons.
 */
@customElement('sgs-geocatalog')
export class SgsGeocatalog extends LitElement {
  static override styles = css`
    :host {
      display: block;
      padding: 1rem;
      overflow-y: auto;
      min-height: 0;
      font-size: 0.875rem;
    }

    .topic-row {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 0.625rem;
    }

    .topic-row label {
      color: var(--sgc-color-text--secondary, #4b5a68);
    }

    select {
      flex: 1;
      font: inherit;
      padding: 0.375rem 0.5rem;
      border: 1px solid var(--sgc-color-border, #d5dbe0);
      border-radius: 0.25rem;
      background: var(--sgc-color-bg--white, #ffffff);
    }

    input[type='search'] {
      width: 100%;
      box-sizing: border-box;
      font: inherit;
      padding: 0.5rem 0.625rem;
      border: 1px solid var(--sgc-color-border, #d5dbe0);
      border-radius: 0.25rem;
      margin-bottom: 0.625rem;
    }

    input[type='search']:focus,
    select:focus {
      outline: 2px solid var(--sgc-color-brand, #d8232a);
      outline-offset: -1px;
    }

    .status {
      color: var(--sgc-color-text--secondary, #4b5a68);
      margin: 0.5rem 0 0;
    }

    ul {
      list-style: none;
      margin: 0;
      padding: 0;
    }

    ul ul {
      padding-left: 1rem;
    }

    .folder > button {
      display: flex;
      align-items: center;
      gap: 0.375rem;
      width: 100%;
      border: none;
      background: none;
      font: inherit;
      text-align: left;
      padding: 0.3125rem 0.25rem;
      border-radius: 0.25rem;
      cursor: pointer;
    }

    .folder > button:hover {
      background: var(--sgc-color-bg--grey, #f0f2f4);
    }

    .twisty {
      flex: none;
      width: 0.875rem;
      color: var(--sgc-color-text--secondary, #4b5a68);
      transition: transform 0.12s;
    }

    .twisty[data-open] {
      transform: rotate(90deg);
    }

    .leaf {
      display: flex;
      align-items: center;
      gap: 0.375rem;
      padding: 0.25rem 0.25rem 0.25rem 1.25rem;
    }

    .leaf .label {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .leaf .label[data-added] {
      color: var(--sgc-color-text--disabled, #98a6b3);
    }

    .add {
      flex: none;
      display: grid;
      place-items: center;
      width: 1.5rem;
      height: 1.5rem;
      border: 1px solid var(--sgc-color-border, #d5dbe0);
      border-radius: 0.25rem;
      background: var(--sgc-color-bg--white, #ffffff);
      font-size: 1rem;
      line-height: 1;
      cursor: pointer;
      color: var(--sgc-color-text, #1c2834);
    }

    .add:hover:not(:disabled) {
      border-color: var(--sgc-color-brand, #d8232a);
      color: var(--sgc-color-brand, #d8232a);
    }

    .add:disabled {
      color: var(--sgc-color-text--disabled, #98a6b3);
      cursor: default;
    }

    .notice {
      font-size: 0.75rem;
      color: var(--sgc-color-brand, #d8232a);
      padding: 0 0.25rem 0.25rem 1.25rem;
    }
  `;

  @consume({ context: catalogServiceContext })
  private catalogService!: CatalogService;

  @consume({ context: layerServiceContext })
  private layerService!: LayerService;

  @state() private topic = DEFAULT_TOPIC;
  @state() private query = '';
  @state() private expanded = new Set<number>();
  @state() private notice?: { layerBodId: string; result: AddLayerResult };

  private noticeHandle?: ReturnType<typeof setTimeout>;

  private readonly language = new ObservableController(this, languageChanged$);

  private readonly topicsTask = new Task(this, {
    args: () => [] as const,
    task: () => this.catalogService.getTopics(),
  });

  private readonly treeTask = new Task(this, {
    args: () => [this.topic, this.language.value ?? currentLanguage()] as const,
    task: ([topic, lang]) => this.catalogService.getCatalogTree(topic, lang),
  });

  override connectedCallback(): void {
    super.connectedCallback();
    // Refresh added-states when the active layers change.
    new ObservableController(this, this.layerService.layers$);
  }

  override render() {
    return html`
      <div class="topic-row">
        <label for="topic">${t('geocatalog.topic')}</label>
        <select id="topic" @change=${this.onTopicChange}>
          ${(this.topicsTask.value ?? [{ id: DEFAULT_TOPIC }]).map(
            (topic) => html`
              <option value=${topic.id} ?selected=${topic.id === this.topic}>${topic.id}</option>
            `,
          )}
        </select>
      </div>
      <input
        type="search"
        placeholder=${t('geocatalog.filterPlaceholder')}
        aria-label=${t('geocatalog.filterPlaceholder')}
        @input=${(e: Event) => (this.query = (e.target as HTMLInputElement).value)}
      />
      ${this.treeTask.render({
        pending: () => html`<p class="status">${t('geocatalog.loading')}</p>`,
        error: () => html`<p class="status">${t('geocatalog.error')}</p>`,
        complete: (root) => this.renderTree(root),
      })}
    `;
  }

  private renderTree(root: CatalogFolderNode) {
    const filtering = this.query.trim().length > 0;
    const tree = filterCatalogTree(root, this.query);
    if (!tree) {
      return html`<p class="status">${t('geocatalog.noMatches')}</p>`;
    }
    return html`<ul>
      ${tree.children.map((node) => this.renderNode(node, filtering))}
    </ul>`;
  }

  private renderNode(node: CatalogNode, filtering: boolean): unknown {
    if (node.kind === 'layer') {
      return this.renderLeaf(node);
    }
    const open = filtering || this.expanded.has(node.id);
    return html`
      <li class="folder">
        <button aria-expanded=${open} @click=${() => this.toggleFolder(node.id)}>
          <span class="twisty" ?data-open=${open}>▸</span>
          <span>${node.label}</span>
        </button>
        ${open
          ? html`<ul>
              ${node.children.map((child) => this.renderNode(child, filtering))}
            </ul>`
          : nothing}
      </li>
    `;
  }

  private renderLeaf(node: CatalogLayerNode) {
    const added = this.layerService.isActive(node.layerBodId);
    const notice = this.notice?.layerBodId === node.layerBodId ? this.notice : undefined;
    return html`
      <li>
        <div class="leaf">
          <span class="label" title=${node.label} ?data-added=${added}>${node.label}</span>
          <button
            class="add"
            ?disabled=${added}
            title=${added ? t('geocatalog.added') : t('geocatalog.add')}
            aria-label=${added ? t('geocatalog.added') : t('geocatalog.add')}
            @click=${() => void this.addLayer(node.layerBodId)}
          >
            ${added ? '✓' : '+'}
          </button>
        </div>
        ${notice ? html`<p class="notice">${t('geocatalog.unsupported')}</p>` : nothing}
      </li>
    `;
  }

  private toggleFolder(id: number): void {
    const expanded = new Set(this.expanded);
    if (expanded.has(id)) {
      expanded.delete(id);
    } else {
      expanded.add(id);
    }
    this.expanded = expanded;
  }

  private async addLayer(layerBodId: string): Promise<void> {
    const result = await this.layerService.addOfficialLayer(layerBodId);
    if (result === 'unsupported' || result === 'unknown') {
      clearTimeout(this.noticeHandle);
      this.notice = { layerBodId, result };
      this.noticeHandle = setTimeout(() => (this.notice = undefined), 4000);
    }
  }

  private onTopicChange(event: Event): void {
    this.topic = (event.target as HTMLSelectElement).value;
    this.expanded = new Set();
    this.query = '';
    const input = this.renderRoot.querySelector<HTMLInputElement>('input[type=search]');
    if (input) {
      input.value = '';
    }
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-geocatalog': SgsGeocatalog;
  }
}
