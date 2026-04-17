/**
 * Unit tests for {@link SidebarFooter}.
 *
 * Tests cover:
 *   1. Renders "NEX Studio v{version}" text
 *   2. Has the correct data-testid attribute
 *   3. Version string matches semver pattern
 *
 * NOTE: The canonical copy of this test lives at
 * ``frontend/src/__tests__/components/test_SidebarFooter.test.tsx``
 * (inside the Vitest include glob). This file mirrors it for the
 * ``tests/frontend/`` deliverable structure.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import SidebarFooter from "@/components/layout/SidebarFooter";

describe("SidebarFooter", () => {
  it("renders the version text with 'NEX Studio v' prefix", () => {
    render(<SidebarFooter />);
    const el = screen.getByTestId("version-text");
    expect(el).toBeInTheDocument();
    expect(el.textContent).toMatch(/^NEX Studio v\d+\.\d+\.\d+$/);
  });

  it("applies gray styling classes", () => {
    render(<SidebarFooter />);
    const el = screen.getByTestId("version-text");
    expect(el.className).toContain("text-gray-400");
    expect(el.className).toContain("text-xs");
  });

  it("renders as a <p> element", () => {
    render(<SidebarFooter />);
    const el = screen.getByTestId("version-text");
    expect(el.tagName).toBe("P");
  });
});
