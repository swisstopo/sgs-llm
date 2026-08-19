import { BehaviorSubject } from 'rxjs';
import type { Observable } from 'rxjs';

/** Flyout panels reachable from the navigation rail. */
export type PanelId = 'chat' | 'maps' | 'catalog' | 'feedback' | 'about';

/** A request to show the layer-info dialog for an official layer. */
export interface LayerInfoRequest {
  /** Layer id (`layerBodId`). */
  id: string;
  /** Display label when the caller already knows it (catalog node, layer row). */
  label?: string;
}

export const CHAT_ONBOARDING_STORAGE_KEY = 'sgs-llm.chat-onboarding.accepted';
export const CHAT_ONBOARDING_VERSION = 'v2';

type OnboardingStorage = Pick<Storage, 'getItem' | 'setItem'>;

/** Shell UI state: which flyout panel is open (one at a time), open dialogs. */
export class UiService {
  private readonly activePanelSubject = new BehaviorSubject<PanelId | null>(null);
  private readonly layerInfoSubject = new BehaviorSubject<LayerInfoRequest | null>(null);
  private readonly chatOnboardingSubject = new BehaviorSubject<boolean>(false);
  private chatOnboardingAcceptedInSession = false;

  constructor(
    private readonly storage: OnboardingStorage | undefined = typeof localStorage === 'undefined'
      ? undefined
      : localStorage,
  ) {
    this.chatOnboardingSubject.next(!this.hasAcceptedChatOnboarding());
  }

  get activePanel$(): Observable<PanelId | null> {
    return this.activePanelSubject.asObservable();
  }

  get activePanel(): PanelId | null {
    return this.activePanelSubject.value;
  }

  /** Opens the panel, or closes it when it is already active. */
  togglePanel(id: PanelId): void {
    if (this.activePanelSubject.value === id) {
      this.activePanelSubject.next(null);
      return;
    }
    if (id === 'chat' && !this.hasAcceptedChatOnboarding()) {
      this.chatOnboardingSubject.next(true);
      return;
    }
    this.activePanelSubject.next(id);
  }

  closePanel(): void {
    this.activePanelSubject.next(null);
  }

  get layerInfo$(): Observable<LayerInfoRequest | null> {
    return this.layerInfoSubject.asObservable();
  }

  get layerInfo(): LayerInfoRequest | null {
    return this.layerInfoSubject.value;
  }

  openLayerInfo(request: LayerInfoRequest): void {
    this.layerInfoSubject.next(request);
  }

  closeLayerInfo(): void {
    this.layerInfoSubject.next(null);
  }

  get chatOnboarding$(): Observable<boolean> {
    return this.chatOnboardingSubject.asObservable();
  }

  get chatOnboardingOpen(): boolean {
    return this.chatOnboardingSubject.value;
  }

  acceptChatOnboarding(): void {
    this.chatOnboardingAcceptedInSession = true;
    try {
      this.storage?.setItem(CHAT_ONBOARDING_STORAGE_KEY, CHAT_ONBOARDING_VERSION);
    } catch {
      // Storage can be unavailable in privacy modes; acceptance still lasts this session.
    }
    this.chatOnboardingSubject.next(false);
    this.activePanelSubject.next('chat');
  }

  private hasAcceptedChatOnboarding(): boolean {
    if (this.chatOnboardingAcceptedInSession) {
      return true;
    }
    try {
      return this.storage?.getItem(CHAT_ONBOARDING_STORAGE_KEY) === CHAT_ONBOARDING_VERSION;
    } catch {
      return false;
    }
  }
}
