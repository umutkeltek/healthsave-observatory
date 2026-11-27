// One write at a time for controls that each read a cookie and write it back
// (components/DashboardCustomizer.tsx): a second write started before the
// first lands would work from the old cookie. While one is in flight, run()
// refuses another (returns null) and isBusy() is true, which the controls
// show. Client-safe; React reads it through useSyncExternalStore.
export class WriteGate {
  private busy = false;
  private readonly listeners = new Set<() => void>();

  isBusy = (): boolean => this.busy;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private set(busy: boolean) {
    this.busy = busy;
    for (const listener of this.listeners) listener();
  }

  async run<T>(write: () => Promise<T>): Promise<T | null> {
    if (this.busy) return null;
    this.set(true);
    try {
      return await write();
    } finally {
      this.set(false);
    }
  }
}
