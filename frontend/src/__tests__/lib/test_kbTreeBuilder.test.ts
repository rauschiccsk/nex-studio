/**
 * Unit tests for ``buildTree`` — pure flat → hierarchical transformation.
 *
 * AC4 (folder/file sort): folders before files in the same level,
 *                          alphabetic within each group.
 * AC7 (RBAC): ``hideCredentials`` option drops the ``credentials/``
 *             top-level branch.
 * AC12: ``credentials`` filter cascades — sub-files under ``credentials/``
 *       also dropped.
 */

import { describe, expect, it } from "vitest";

import { buildTree } from "@/lib/kbTreeBuilder";
import type { KnowledgeDoc, TreeNode } from "@/types/knowledge";

function doc(relative_path: string): KnowledgeDoc {
  const parts = relative_path.split("/");
  const filename = parts[parts.length - 1] as string;
  const category = parts.slice(0, -1).join("/") || "";
  return { relative_path, filename, category, size_bytes: 100 };
}

/** Narrow a tree node to a folder or throw — keeps strict-TS happy in tests. */
function asFolder(
  node: TreeNode | undefined,
): Extract<TreeNode, { type: "folder" }> {
  if (!node || node.type !== "folder") {
    throw new Error(`expected folder, got ${node?.type ?? "undefined"}`);
  }
  return node;
}

describe("buildTree", () => {
  it("returns empty array for empty input", () => {
    expect(buildTree([])).toEqual([]);
  });

  it("renders a single root file (no parent folder)", () => {
    const tree = buildTree([doc("README.md")]);
    expect(tree).toHaveLength(1);
    expect(tree[0]).toMatchObject({
      type: "file",
      path: "README.md",
      name: "README.md",
      depth: 0,
    });
  });

  it("renders a single nested file (one folder wrap)", () => {
    const tree = buildTree([doc("icc/STANDARDS.md")]);
    expect(tree).toHaveLength(1);
    const iccFolder = asFolder(tree[0]);
    expect(iccFolder).toMatchObject({
      type: "folder",
      path: "icc",
      name: "icc",
      depth: 0,
    });
    expect(iccFolder.children).toHaveLength(1);
    expect(iccFolder.children[0]).toMatchObject({
      type: "file",
      path: "icc/STANDARDS.md",
      name: "STANDARDS.md",
      depth: 1,
    });
  });

  it("groups multiple files under the same folder", () => {
    const tree = buildTree([
      doc("icc/CLAUDE_COMMON.md"),
      doc("icc/STANDARDS.md"),
    ]);
    expect(tree).toHaveLength(1);
    const iccFolder = asFolder(tree[0]);
    expect(iccFolder.children).toHaveLength(2);
    expect(iccFolder.children.map((c) => c.name)).toEqual([
      "CLAUDE_COMMON.md",
      "STANDARDS.md",
    ]);
  });

  it("handles deep nesting (projects/nex-inbox/STATUS.md)", () => {
    const tree = buildTree([doc("projects/nex-inbox/STATUS.md")]);
    expect(tree).toHaveLength(1);
    const projectsFolder = asFolder(tree[0]);
    expect(projectsFolder.path).toBe("projects");
    expect(projectsFolder.depth).toBe(0);

    const nexInboxFolder = asFolder(projectsFolder.children[0]);
    expect(nexInboxFolder.path).toBe("projects/nex-inbox");
    expect(nexInboxFolder.depth).toBe(1);

    expect(nexInboxFolder.children[0]).toMatchObject({
      type: "file",
      path: "projects/nex-inbox/STATUS.md",
      name: "STATUS.md",
      depth: 2,
    });
  });

  it("sorts folders before files at same level (AC4)", () => {
    const tree = buildTree([
      doc("README.md"),
      doc("icc/A.md"),
      doc("CHANGELOG.md"),
      doc("infrastructure/B.md"),
    ]);
    expect(tree.map((n) => n.name)).toEqual([
      "icc", // folder (sorted alphabetically)
      "infrastructure", // folder
      "CHANGELOG.md", // file
      "README.md", // file
    ]);
  });

  it("sorts files alphabetically within a folder", () => {
    const tree = buildTree([
      doc("icc/Z.md"),
      doc("icc/A.md"),
      doc("icc/M.md"),
    ]);
    const iccFolder = asFolder(tree[0]);
    expect(iccFolder.children.map((c) => c.name)).toEqual([
      "A.md",
      "M.md",
      "Z.md",
    ]);
  });

  it("hides credentials/ branch when hideCredentials=true (AC7)", () => {
    const tree = buildTree(
      [
        doc("icc/STANDARDS.md"),
        doc("credentials/db.md"),
        doc("credentials/api/key.md"),
      ],
      { hideCredentials: true },
    );
    expect(tree.map((n) => n.name)).toEqual(["icc"]);
  });

  it("includes credentials/ branch when hideCredentials=false (default)", () => {
    const tree = buildTree([
      doc("icc/STANDARDS.md"),
      doc("credentials/db.md"),
    ]);
    expect(tree.map((n) => n.name).sort()).toEqual(["credentials", "icc"]);
  });

  it("attaches KnowledgeDoc to leaf nodes for downstream consumers", () => {
    const inputDoc = doc("icc/X.md");
    const tree = buildTree([inputDoc]);
    const iccFolder = asFolder(tree[0]);
    const leaf = iccFolder.children[0];
    if (!leaf || leaf.type !== "file") throw new Error("expected file leaf");
    expect(leaf.doc).toBe(inputDoc);
  });

  it("interleaves folders and files at multiple depths correctly", () => {
    const tree = buildTree([
      doc("icc/STANDARDS.md"),
      doc("icc/sub/A.md"),
      doc("icc/sub/B.md"),
      doc("icc/Z.md"),
    ]);
    const iccFolder = asFolder(tree[0]);
    // icc/ children: sub/ (folder), STANDARDS.md, Z.md
    expect(iccFolder.children.map((c) => c.name)).toEqual([
      "sub",
      "STANDARDS.md",
      "Z.md",
    ]);
  });
});
