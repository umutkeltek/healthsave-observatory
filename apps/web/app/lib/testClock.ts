// Test helper: fake both clocks. at(ms) moves the monotonic clock
// (performance.now) and the wall clock (Date.now) together, ms after start;
// stepWallBack(ms) moves only the wall clock back, as a VM resume or an NTP
// correction does. Imported by tests only; they pass bun:test's setSystemTime
// (this file is typechecked with the app, which has no bun:test types).
type SetSystemTime = (time?: number | Date) => unknown;

export function fakeClocks(start: number, setSystemTime: SetSystemTime) {
  const realNow = performance.now;
  let mono = 0;
  let wallOffset = 0;
  performance.now = () => mono;
  const apply = () => setSystemTime(start + mono + wallOffset);
  apply();
  return {
    at(ms: number) {
      mono = ms;
      apply();
    },
    stepWallBack(ms: number) {
      wallOffset -= ms;
      apply();
    },
    restore() {
      performance.now = realNow;
      setSystemTime();
    },
  };
}
