import { BehaviorSubject } from 'rxjs';
import type { Observable } from 'rxjs';

/** Flyout panels reachable from the navigation rail. */
export type PanelId = 'search' | 'maps' | 'catalog' | 'chat' | 'feedback' | 'about';

/** Shell UI state: which flyout panel is open (one at a time). */
export class UiService {
  private readonly activePanelSubject = new BehaviorSubject<PanelId | null>(null);

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
}
