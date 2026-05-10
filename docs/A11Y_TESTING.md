# A11y Testing Guide

This project uses **axe-core** (via `jest-axe`) to detect accessibility
violations in unit tests.

`jest-axe` is the mature, actively maintained axe-core wrapper for test runners.
Despite the "jest" name it works with **Vitest** (no Jest runtime is included).

## Adding an a11y test

```typescript
import { axe } from "jest-axe";
import { render } from "@testing-library/react";

it("has no axe-core violations", async () => {
  const { container } = render(
    <MyComponent aria-label="Descriptive label" />
  );
  const results = await axe(container, {
    // Color contrast requires canvas — disable in JSDOM (see Limitations).
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results).toHaveNoViolations();
});
```

The `toHaveNoViolations` matcher is registered globally in `vitest.setup.ts`
(via `expect.extend(toHaveNoViolations)`). No per-file import of the matcher
is needed — only `axe` must be imported from `jest-axe`.

## What axe-core checks

- Color contrast (WCAG AA/AAA) — disabled in JSDOM, see Limitations
- ARIA role validity (`aria-allowed-role`)
- Required ARIA attributes (`aria-required-attr`)
- Keyboard accessibility (focusable elements, tab index)
- Form labels and accessible names
- Heading hierarchy
- List structure validity
- Image alt text
- And ~70+ other rules ([full rule list](https://github.com/dequelabs/axe-core/blob/develop/doc/rule-descriptions.md))

## Render with realistic props

Always render components as they would appear in real usage — with labels,
`aria-label`, accessible names, etc. Rendering a component without required
a11y props is a test-setup error, not a real violation:

```typescript
// BAD — axe will flag missing accessible name (false negative for our usage):
render(<GlassInput />);

// GOOD — renders as intended:
render(<GlassInput label="Email address" type="email" />);
```

## Handling genuine violations

If axe finds a **real** violation in a component:

1. **Do NOT mask it** with `axe(container, { rules: { 'bad-rule': { enabled: false } } })`.
2. **Skip the test** with `it.skip(...)`.
3. **Document the finding** in a comment explaining:
   - What the violation is
   - Which axe rule fires
   - Root cause
   - Options for fixing it
   - Tracking reference (issue or PR)

Example:

```typescript
// FINDING: aria-allowed-role — <li role="status"> not valid.
// Root cause: Radix Toast.Root renders as <li>; role override is illegal.
// Fix options: remove explicit role=, rely on Radix type prop + aria-live.
// Tracked: follow-up PR after I3.6.
it.skip("toast has no violations [FINDING: see comment]", async () => {
  ...
});
```

## Limitations

### Color contrast

axe-core cannot measure computed CSS colors without a real canvas implementation.
In JSDOM, color-contrast checks produce inconsistent results (false positives
when using CSS variables or `rgba` with opacity).

**Always disable color-contrast in unit tests:**

```typescript
const results = await axe(container, {
  rules: { "color-contrast": { enabled: false } },
});
```

Full contrast testing requires a real browser. This is tracked as **I3.7**
(Playwright + `@axe-core/playwright`).

### Focus visibility

CSS `:focus-visible` outline checking is partially supported in JSDOM but
unreliable. Focus trap correctness is better tested with `userEvent.tab()`
(as done in `AdminModal.test.tsx`).

### Dynamic/animated content

axe-core checks the DOM snapshot at call time. For components with open/close
animations, call `axe` after the component is fully mounted (e.g., after
`await new Promise(r => setTimeout(r, 0))` if Radix uses deferred portal mounting).

### Server-side rendering

axe-core only works with rendered DOM. For SSR validation, use axe-playwright
or Pa11y against a running server.

## Known findings (I3.6)

| Component      | Rule                | Severity | Status | Notes |
|---------------|---------------------|----------|--------|-------|
| GlassToast    | `aria-allowed-role` | Serious  | Skipped | `role="status/alert"` on `<li>` — Radix Toast.Root renders as `<li>`. Requires removing explicit `role=` prop and relying on Radix `type` + `aria-live` defaults. |
| GlassToast    | `list`              | Serious  | Skipped | `<ol>` Viewport contains `<li role="status/alert">` children directly. Consequence of above. |

These findings are **out of scope for I3.6** (infra-only). Fix tracked as a
follow-up: replace explicit `role=` on `Toast.Root` with proper `type=` prop
control only, letting Radix manage the implicit ARIA semantics.

## For future I3.7 — Playwright a11y

Once I3.7 is implemented, add browser-level tests using:

```typescript
import { checkA11y } from "axe-playwright";

test("page has no a11y violations", async ({ page }) => {
  await page.goto("/admin");
  await checkA11y(page, undefined, {
    detailedReport: true,
    detailedReportOptions: { html: true },
  });
});
```

This enables real color-contrast checking, focus visibility, and full
keyboard navigation testing against a live Next.js app.
