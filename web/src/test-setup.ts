/**
 * Shared test setup.
 *
 * **`ResizeObserver` is stubbed because jsdom does not implement it and React Flow requires it.**
 * That is a gap in the test environment, not in the app: a browser has one. Stubbing it lets a
 * canvas mount so the paths that are *logic* — the size refusal, the loading transition — can be
 * exercised, while anything that depends on real layout still cannot be, because jsdom does no
 * layout. The stub does nothing on purpose: a fake that reported sizes would make the canvas
 * appear to work in a place where it cannot.
 */
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@testing-library/jest-dom/vitest";

/**
 * Unmount between tests.
 *
 * React Testing Library registers this itself **only when Vitest's globals are on**, and they are
 * off here. Without it the previous test's DOM stays mounted, and the next test's queries run
 * against two renders at once — which does not fail loudly, it fails confusingly: a `queryByText`
 * that should find nothing finds the previous test's element, and the test reports a bug in the
 * app rather than in the harness.
 */
afterEach(cleanup);

class NoopResizeObserver implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (!("ResizeObserver" in globalThis)) {
  Object.defineProperty(globalThis, "ResizeObserver", {
    value: NoopResizeObserver,
    writable: true,
  });
}

if (!("DOMRectReadOnly" in globalThis)) {
  class StubRect {
    static fromRect(): StubRect {
      return new StubRect();
    }
    readonly x = 0;
    readonly y = 0;
    readonly width = 0;
    readonly height = 0;
    readonly top = 0;
    readonly left = 0;
    readonly right = 0;
    readonly bottom = 0;
  }
  Object.defineProperty(globalThis, "DOMRectReadOnly", { value: StubRect, writable: true });
}
