/**
 * Pure builder: flat ``KnowledgeDoc[]`` → hierarchical ``TreeNode[]``.
 *
 * Used by :file:`KbTree.tsx` to render the unified file-browser sidebar.
 * Stateless and deterministic — covered by
 * :file:`src/__tests__/lib/test_kbTreeBuilder.test.ts`.
 *
 * Sort order (per AC4 in the design spec):
 *   1. Folders first within each level, alphabetically.
 *   2. Files after folders within the same level, alphabetically.
 *
 * Depth is 0-indexed and reflects the level in the rendered tree
 * (top-level nodes are depth 0).
 *
 * Credentials filter (per AC7): when ``hideCredentials=true`` is set
 * (non-ri roles), the entire ``credentials/`` top-level branch is dropped
 * before tree construction so no leaked path appears in the UI.
 */

import type { KnowledgeDoc, TreeNode } from "@/types/knowledge";

interface BuildTreeOptions {
  hideCredentials?: boolean;
}

export function buildTree(
  documents: KnowledgeDoc[],
  options: BuildTreeOptions = {},
): TreeNode[] {
  const { hideCredentials = false } = options;

  const filtered = hideCredentials
    ? documents.filter((d) => !d.relative_path.startsWith("credentials/"))
    : documents;

  const root: TreeNode[] = [];
  const folderIndex = new Map<string, TreeNode>();

  for (const doc of filtered) {
    const parts = doc.relative_path.split("/");
    if (parts.length === 0) continue;
    // split("/") always yields at least one element, so non-null is safe.
    const fileName = parts[parts.length - 1] as string;
    const folderParts = parts.slice(0, -1);

    // Walk / create folders along the path.
    let parentChildren = root;
    let cumulativePath = "";
    for (let depth = 0; depth < folderParts.length; depth++) {
      const segment = folderParts[depth] as string;
      cumulativePath = cumulativePath ? `${cumulativePath}/${segment}` : segment;

      let folder: TreeNode | undefined = folderIndex.get(cumulativePath);
      if (folder === undefined) {
        const newFolder: TreeNode = {
          type: "folder",
          path: cumulativePath,
          name: segment,
          depth,
          children: [],
        };
        folderIndex.set(cumulativePath, newFolder);
        parentChildren.push(newFolder);
        folder = newFolder;
      }
      if (folder.type !== "folder") {
        // Defensive: a previously-seen file path now treated as folder.
        throw new Error(
          `kbTreeBuilder: path collision at ${cumulativePath} (folder vs file)`,
        );
      }
      parentChildren = folder.children;
    }

    // Attach the leaf file under the (possibly empty) folder parent.
    parentChildren.push({
      type: "file",
      path: doc.relative_path,
      name: fileName,
      depth: folderParts.length,
      doc,
    });
  }

  sortInPlace(root);
  return root;
}

/**
 * Sort folders first, then files; alphabetically within each group.
 * Recurses into folder children.
 */
function sortInPlace(nodes: TreeNode[]): void {
  nodes.sort((a, b) => {
    if (a.type !== b.type) {
      return a.type === "folder" ? -1 : 1;
    }
    return a.name.localeCompare(b.name);
  });
  for (const node of nodes) {
    if (node.type === "folder") {
      sortInPlace(node.children);
    }
  }
}
