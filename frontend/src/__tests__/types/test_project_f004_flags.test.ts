/**
 * F-004 flags compile-time tests pre ProjectCreate type.
 *
 * Verifies že 4 F-004 boolean flags sú accepted by TypeScript v ProjectCreate
 * payload type (used by createProjectApi).
 */

import { describe, it, expect } from "vitest";
import type { ProjectCreate } from "@/types/project";

describe("ProjectCreate F-004 setup flags", () => {
  it("accepts all 4 setup flags with explicit values", () => {
    const payload: ProjectCreate = {
      name: "Test",
      slug: "test",
      category: "singlemodule",
      description: "F-004 test",
      created_by: "user-uuid",
      enable_coordinator: true,
      enable_cicd: true,
      full_smoke: true,
      enable_branch_protection: true,
    };

    expect(payload.enable_coordinator).toBe(true);
    expect(payload.enable_cicd).toBe(true);
    expect(payload.full_smoke).toBe(true);
    expect(payload.enable_branch_protection).toBe(true);
  });

  it("flags are optional — payload bez nich je platný", () => {
    const payload: ProjectCreate = {
      name: "Minimal",
      slug: "minimal",
      category: "singlemodule",
      description: "",
      created_by: "user-uuid",
    };

    expect(payload.enable_coordinator).toBeUndefined();
    expect(payload.enable_cicd).toBeUndefined();
    expect(payload.full_smoke).toBeUndefined();
    expect(payload.enable_branch_protection).toBeUndefined();
  });

  it("F-004 spec defaults: coordinator=true, others=false", () => {
    // Default policy podľa spec §4 form: enable_coordinator ON, ostatné OFF
    const payload: ProjectCreate = {
      name: "Defaults",
      slug: "defaults",
      category: "singlemodule",
      description: "",
      created_by: "user-uuid",
      enable_coordinator: true, // default ON
      enable_cicd: false, // default OFF
      full_smoke: false, // default OFF
      enable_branch_protection: false, // default OFF (per Q-7 Dedo approval)
    };

    expect(payload.enable_coordinator).toBe(true);
    expect(payload.enable_cicd).toBe(false);
    expect(payload.full_smoke).toBe(false);
    expect(payload.enable_branch_protection).toBe(false);
  });
});
