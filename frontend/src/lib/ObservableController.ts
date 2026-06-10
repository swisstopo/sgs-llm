import type { ReactiveController, ReactiveControllerHost } from 'lit';
import type { Observable, Subscription } from 'rxjs';

/**
 * Bridges an RxJS observable into Lit's reactive update cycle: the host
 * re-renders on every emission and the subscription follows the host's
 * connected lifecycle.
 */
export class ObservableController<T> implements ReactiveController {
  value?: T;

  private subscription?: Subscription;

  constructor(
    private readonly host: ReactiveControllerHost,
    private readonly observable: Observable<T>,
  ) {
    host.addController(this);
  }

  hostConnected(): void {
    this.subscription = this.observable.subscribe((value) => {
      this.value = value;
      this.host.requestUpdate();
    });
  }

  hostDisconnected(): void {
    this.subscription?.unsubscribe();
    this.subscription = undefined;
  }
}
