/**
 * axe-core a11y tests — Liquid Glass primitives (I3.6)
 *
 * Verifies that key liquid-glass primitives have no axe-core violations when
 * rendered with realistic, representative props.
 *
 * Notes:
 *  - color-contrast is disabled globally in this file: JSDOM has no canvas
 *    and cannot measure computed CSS colors. False positives are expected.
 *    Full contrast checks are tracked as I3.7 (Playwright + axe-playwright).
 *  - Each component is tested in its "intended usage" form (with labels,
 *    aria-labels, etc.). Rendering a component without required a11y props
 *    is a test-setup error, not a real bug.
 *  - If axe flags a genuine violation in a primitive, it is noted as a
 *    finding comment and the test is marked `.skip` with a tracking reference.
 *    DO NOT mask violations silently.
 */

import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { axe } from "jest-axe";
import {
  GlassButton,
  GlassCard,
  GlassInput,
  GlassPill,
  GlassSection,
  GlassRow,
  GlassSurface,
  GlassTabs,
  GlassSwitch,
  GlassModal,
} from "../primitives";
import { GlassToastProvider } from "../toast";

// Shared axe options — disable color-contrast for all primitives tests.
const axeOptions = {
  rules: { "color-contrast": { enabled: false } },
};

/* ──────────────────────────────────────────────────────────────────
   GlassButton
   ────────────────────────────────────────────────────────────────── */

describe("GlassButton a11y", () => {
  it("primary button with text label has no violations", async () => {
    const { container } = render(
      <GlassButton variant="primary">Save changes</GlassButton>
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it("ghost button with aria-label (icon button) has no violations", async () => {
    const { container } = render(
      <GlassButton variant="ghost" aria-label="Close dialog">
        ✕
      </GlassButton>
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it("danger button has no violations", async () => {
    const { container } = render(
      <GlassButton variant="danger">Delete account</GlassButton>
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it("disabled button has no violations", async () => {
    const { container } = render(
      <GlassButton variant="primary" disabled>
        Saving…
      </GlassButton>
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });
});

/* ──────────────────────────────────────────────────────────────────
   GlassInput
   ────────────────────────────────────────────────────────────────── */

describe("GlassInput a11y", () => {
  it("labelled input has no violations", async () => {
    const { container } = render(
      <GlassInput label="Email address" type="email" placeholder="you@example.com" />
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it("input with error message has no violations", async () => {
    const { container } = render(
      <GlassInput
        label="Username"
        error="Username is already taken"
        defaultValue="taken_user"
      />
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it("input with hint has no violations", async () => {
    const { container } = render(
      <GlassInput
        label="Password"
        type="password"
        hint="Must be at least 8 characters"
      />
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });
});

/* ──────────────────────────────────────────────────────────────────
   GlassTabs
   ────────────────────────────────────────────────────────────────── */

describe("GlassTabs a11y", () => {
  const tabs = [
    { value: "profile", label: "Profile" },
    { value: "security", label: "Security" },
    { value: "billing", label: "Billing" },
  ];

  it("tablist with aria-label has no violations", async () => {
    const { container } = render(
      <GlassTabs
        tabs={tabs}
        value="profile"
        onChange={() => {}}
        aria-label="Account settings"
      />
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });
});

/* ──────────────────────────────────────────────────────────────────
   GlassSwitch
   ────────────────────────────────────────────────────────────────── */

describe("GlassSwitch a11y", () => {
  it("checked switch with aria-label has no violations", async () => {
    const { container } = render(
      <GlassSwitch
        checked={true}
        onChange={() => {}}
        aria-label="Enable notifications"
      />
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it("unchecked switch with aria-label has no violations", async () => {
    const { container } = render(
      <GlassSwitch
        checked={false}
        onChange={() => {}}
        aria-label="Enable dark mode"
      />
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it("disabled switch has no violations", async () => {
    const { container } = render(
      <GlassSwitch
        checked={false}
        onChange={() => {}}
        aria-label="Feature flag (admin only)"
        disabled
      />
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });
});

/* ──────────────────────────────────────────────────────────────────
   GlassCard
   ────────────────────────────────────────────────────────────────── */

describe("GlassCard a11y", () => {
  it("card with text content has no violations", async () => {
    const { container } = render(
      <GlassCard>
        <p>Welcome to your dashboard.</p>
      </GlassCard>
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });
});

/* ──────────────────────────────────────────────────────────────────
   GlassSurface
   ────────────────────────────────────────────────────────────────── */

describe("GlassSurface a11y", () => {
  it("plain surface with content has no violations", async () => {
    const { container } = render(
      <GlassSurface variant="plain">
        <span>Content</span>
      </GlassSurface>
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });
});

/* ──────────────────────────────────────────────────────────────────
   GlassPill
   ────────────────────────────────────────────────────────────────── */

describe("GlassPill a11y", () => {
  it("default pill has no violations", async () => {
    const { container } = render(<GlassPill>Admin</GlassPill>);
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it("danger pill has no violations", async () => {
    const { container } = render(<GlassPill tone="danger">Banned</GlassPill>);
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });
});

/* ──────────────────────────────────────────────────────────────────
   GlassSection + GlassRow
   ────────────────────────────────────────────────────────────────── */

describe("GlassSection / GlassRow a11y", () => {
  it("section with title and rows has no violations", async () => {
    const { container } = render(
      <GlassSection title="Account settings" subtitle="Manage your profile">
        <GlassRow label="Display name" value="Alice" />
        <GlassRow label="Email" value="alice@example.com" />
      </GlassSection>
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });
});

/* ──────────────────────────────────────────────────────────────────
   GlassModal (primitive, not AdminModal)
   ────────────────────────────────────────────────────────────────── */

describe("GlassModal a11y", () => {
  it("open modal with title and content has no violations", async () => {
    const { container } = render(
      <GlassModal open onClose={() => {}} title="Confirm action">
        <p>Are you sure you want to proceed?</p>
      </GlassModal>
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it("open modal with footer buttons has no violations", async () => {
    const { container } = render(
      <GlassModal
        open
        onClose={() => {}}
        title="Delete item"
        footer={
          <>
            <GlassButton variant="ghost">Cancel</GlassButton>
            <GlassButton variant="danger">Delete</GlassButton>
          </>
        }
      >
        <p>This action cannot be undone.</p>
      </GlassModal>
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });
});

/* ──────────────────────────────────────────────────────────────────
   GlassToastProvider (viewport scaffold only, no toast triggered)
   ────────────────────────────────────────────────────────────────── */

describe("GlassToastProvider a11y", () => {
  it("empty provider (no toasts) has no violations", async () => {
    const { container } = render(
      <GlassToastProvider>
        <div>App content</div>
      </GlassToastProvider>
    );
    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });
});
