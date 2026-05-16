/**
 * 左侧 folder 树 — 嵌套渲染,只显示 folder(不含 leaf file)。
 * 用 antd Tree component;sensitive folder 用 lock 图标 + 高亮。
 */
import { Tree, Typography } from 'antd';
import { FolderOutlined, FolderOpenOutlined, LockOutlined } from '@ant-design/icons';
import { useMemo } from 'react';
import type { Folder } from '../api/types';

interface Props {
  folders: Folder[];
  projectName?: string;
  activeFolderId: string | null;
  onSelect: (folderId: string) => void;
}

interface TreeNode {
  key: string;
  title: React.ReactNode;
  icon: React.ReactNode;
  children?: TreeNode[];
}

function buildTree(folders: Folder[]): TreeNode[] {
  const byParent = new Map<string | null, Folder[]>();
  for (const f of folders) {
    const k = f.parent_folder_id ?? null;
    const arr = byParent.get(k) ?? [];
    arr.push(f);
    byParent.set(k, arr);
  }
  for (const arr of byParent.values()) arr.sort((a, b) => {
    if (a.is_sensitive !== b.is_sensitive) return a.is_sensitive ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  const build = (parent: string | null): TreeNode[] =>
    (byParent.get(parent) ?? []).map(f => {
      const sub = build(f.id);
      return {
        key: f.id,
        title: (
          <span>
            {f.name}
            {f.is_sensitive && (
              <Typography.Text type="warning" style={{ marginLeft: 6, fontSize: 11 }}>
                <LockOutlined /> 敏感
              </Typography.Text>
            )}
          </span>
        ),
        icon: f.is_sensitive
          ? <LockOutlined style={{ color: '#fa541c' }} />
          : sub.length > 0 ? <FolderOpenOutlined /> : <FolderOutlined />,
        children: sub.length > 0 ? sub : undefined,
      };
    });
  return build(null);
}

export function FolderTree({ folders, projectName, activeFolderId, onSelect }: Props) {
  const tree = useMemo(() => buildTree(folders), [folders]);

  // 计算从根到 active 的所有 expand keys(让 active 可见)
  const defaultExpanded = useMemo(() => {
    if (!activeFolderId) return [];
    const idById = new Map(folders.map(f => [f.id, f] as const));
    const path: string[] = [];
    let cur = idById.get(activeFolderId);
    while (cur?.parent_folder_id) {
      path.push(cur.parent_folder_id);
      cur = idById.get(cur.parent_folder_id);
    }
    return path;
  }, [activeFolderId, folders]);

  if (tree.length === 0) {
    return (
      <div style={{ padding: 16, color: '#999', fontSize: 13 }}>
        {projectName ?? '项目'}没有可见 folder
      </div>
    );
  }

  return (
    <div style={{ padding: '8px 4px' }}>
      {projectName && (
        <Typography.Text strong style={{ display: 'block', padding: '4px 8px', fontSize: 13 }}>
          {projectName}
        </Typography.Text>
      )}
      <Tree
        treeData={tree}
        showIcon
        blockNode
        defaultExpandAll={tree.length < 30}
        defaultExpandedKeys={defaultExpanded}
        selectedKeys={activeFolderId ? [activeFolderId] : []}
        onSelect={(keys) => keys[0] && onSelect(keys[0] as string)}
      />
    </div>
  );
}
