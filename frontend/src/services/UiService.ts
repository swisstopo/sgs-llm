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

/** Shell UI state: which flyout panel is open (one at a time), open dialogs. */
export class UiService {
  private readonly activePanelSubject = new BehaviorSubject<PanelId | null>(null);
  private readonly layerInfoSubject = new BehaviorSubject<LayerInfoRequest | null>(null);

  get activePanel$(): Observable<PanelId | null> {
    return this.activePanelSubject.asObservable();
  }

  get activePanel(): PanelId | null {
    return this.activePanelSubject.value;
  }

  /** Opens the panel, or closes it when it is already active. */
  togglePanel(id: PanelId): void {
    this.activePanelSubject.next(this.activePanelSubject.value === id ? null : id);
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
}
