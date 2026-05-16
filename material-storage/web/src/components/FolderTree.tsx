/**
 * 左侧 folder 树 — 嵌套渲染,只显示 folder(不含 leaf file)。
 * 用 antd Tree component;sensitive folder 用 lock 图标 + 高亮。
 */
import { Button, Space, Tooltip, Tree, Typography } from 'antd';
import { FolderOutlined, FolderOpenOutlined, LockOutlined, PlusOutlined } from '@ant-design/icons';
import { useMemo } from 'react';
import type { Folder } from '../api/types';

interface Props {
  folders: Folder[];
  projectName?: string;
  activeFolderId: string | null;
  onSelect: (folderId: string) => void;
  onCreateChild?: () => void;  // 在 active(或 root)下新建子 folder
  onCreateRoot?: () => void;   // 在 project root 下新建顶层 folder
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

export function FolderTree({
  folders, projectName, activeFolderId, onSelect, onCreateChild, onCreateRoot,
}: Props) {
  const tree = useMemo(() => buildTree(folders), [folders]);

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

  const header = (
    <div style={{ display: 'flex', alignItems: 'center', padding: '4px 8px', gap: 4 }}>
      {projectName && (
        <Typography.Text strong style={{ flex: 1, fontSize: 13 }} ellipsis>{projectName}</Typography.Text>
      )}
      <Space size={2}>
        {onCreateRoot && (
          <Tooltip title="在项目根新建文件夹">
            <Button type="text" size="small" icon={<PlusOutlined />} onClick={onCreateRoot} />
          </Tooltip>
        )}
        {onCreateChild && activeFolderId && (
          <Tooltip title="在当前文件夹下新建子文件夹">
            <Button type="text" size="small" icon={<PlusOutlined />}
                    onClick={onCreateChild}
                    style={{ color: '#1677ff' }}>子</Button>
          </Tooltip>
        )}
      </Space>
    </div>
  );

  if (tree.length === 0) {
    return (
      <div>
        {header}
        <div style={{ padding: 16, color: '#999', fontSize: 13 }}>
          {projectName ?? '项目'}还没文件夹
          {onCreateRoot && (
            <div style={{ marginTop: 8 }}>
              <Button size="small" icon={<PlusOutlined />} onClick={onCreateRoot}>新建文件夹</Button>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: '4px 0' }}>
      {header}
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
