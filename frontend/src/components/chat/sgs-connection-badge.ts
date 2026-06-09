import { LitElement, css, html } from 'lit';
import { customElement } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { agentClientContext } from '../../context';
import type { AgentClient, ConnectionStatus } from '../../agent/AgentClient';
import { ObservableController } from '../../lib/ObservableController';
import { languageChanged$, t } from '../../i18n/i18n';

/** Small agent connection indicator. */
@customElement('sgs-connection-badge')
export class SgsConnectionBadge extends LitElement {
  static override styles = css`
    :host {
      display: inline-flex;
      align-items: center;
      gap: 0.375rem;
      font-size: 0.75rem;
      color: var(--sgc-color-text--secondary, #4b5a68);
    }

    .dot {
      width: 0.5rem;
      height: 0.5rem;
      border-radius: 50%;
    }

    .dot[data-status='open'] {
      background: #2e7d32;
    }

    .dot[data-status='connecting'] {
      background: #f9a825;
    }

    .dot[data-status='closed'] {
      background: var(--sgc-color-brand, #d8232a);
    }
  `;

  @consume({ context: agentClientContext })
  private agentClient!: AgentClient;

  private status?: ObservableController<ConnectionStatus>;

  private readonly _language = new ObservableController(this, languageChanged$);

  override connectedCallback(): void {
    super.connectedCallback();
    this.status ??= new ObservableController(this, this.agentClient.status$);
  }

  override render() {
    const status = this.status?.value ?? this.agentClient.status;
    return html`
      <span class="dot" data-status=${status}></span>
      <span>${t(`chat.connection.${status}`)}</span>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-connection-badge': SgsConnectionBadge;
  }
}
