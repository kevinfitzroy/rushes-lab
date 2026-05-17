/**
 * 左侧 folder 树 — sensitive 用 2px accent 竖条标识 + lucide icons + 紧凑 typography。
 * 沿用 antd Tree 引擎,通过 title 自定义 + components token 调整视觉。
 */
import { Tooltip, Tree } from 'antd';
import { Folder as FolderIcon, FolderOpen, Lock, Plus } from 'lucide-react';
import { useMemo } from 'react';
import type { Folder } from '../api/types';

interface Props {
  folders: Folder[];
  projectName?: string;
  activeFolderId: string | null;
  onSelect: (folderId: string) => void;
  onCreateChild?: () => void;
  onCreateRoot?: () => void;
}

interface TreeNode {
  key: string;
  title: React.ReactNode;
  icon: React.ReactNode;
  isLeaf?: boolean;
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
  for (const arr of byParent.values()) {
    arr.sort((a, b) => {
      // sensitive 排在普通后(更"档案"逻辑)
      if (a.is_sensitive !== b.is_sensitive) return a.is_sensitive ? 1 : -1;
      return a.name.localeCompare(b.name);
    });
  }

  const build = (parent: string | null): TreeNode[] =>
    (byParent.get(parent) ?? []).map(f => {
      const sub = build(f.id);
      return {
        key: f.id,
        title: (
          <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            position: 'relative',
            paddingLeft: f.is_sensitive ? 6 : 0,
            color: 'var(--ms-ink)',
            fontSize: 13,
          }}>
            {f.is_sensitive && (
              <span
                aria-label="敏感目录"
                title="敏感目录 — 仅邀请可见"
                style={{
                  position: 'absolute',
                  left: -2, top: 4, bottom: 4,
                  width: 2,
                  background: 'var(--ms-sensitive)',
                  borderRadius: 1,
                }}
              />
            )}
            <span style={{
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>{f.name}</span>
            {f.is_sensitive && (
              <Lock size={10} strokeWidth={2}
                    style={{ color: 'var(--ms-sensitive)', flexShrink: 0 }} />
            )}
          </span>
        ),
        icon: f.is_sensitive
          ? <FolderIcon size={14} strokeWidth={1.7}
                        style={{ color: 'var(--ms-sensitive)' }} />
          : sub.length > 0
            ? <FolderOpen size={14} strokeWidth={1.7}
                          style={{ color: 'var(--ms-ink-muted)' }} />
            : <FolderIcon size={14} strokeWidth={1.7}
                          style={{ color: 'var(--ms-ink-muted)' }} />,
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

  const Header = (
    <div style={{
      display: 'flex', alignItems: 'center',
      padding: '12px 14px 10px',
      gap: 6,
      borderBottom: '1px solid var(--ms-hairline-soft)',
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
          color: 'var(--ms-ink-subtle)', fontFamily: 'var(--ms-font-mono)',
          fontWeight: 500,
        }}>
          Folders
        </div>
        {projectName && (
          <div style={{
            marginTop: 2,
            fontSize: 13, fontWeight: 500, color: 'var(--ms-ink)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>{projectName}</div>
        )}
      </div>
      {onCreateRoot && (
        <Tooltip title="项目根新建" placement="bottom">
          <button
            onClick={onCreateRoot}
            aria-label="新建一级文件夹"
            style={ghostIconBtn}
            onMouseEnter={e => Object.assign(e.currentTarget.style, ghostIconBtnHover)}
            onMouseLeave={e => Object.assign(e.currentTarget.style, ghostIconBtnRest)}
          >
            <Plus size={14} strokeWidth={2} />
          </button>
        </Tooltip>
      )}
      {onCreateChild && activeFolderId && (
        <Tooltip title="当前文件夹下新建子" placement="bottom">
          <button
            onClick={onCreateChild}
            aria-label="新建子文件夹"
            style={{ ...ghostIconBtn, color: 'var(--ms-accent)' }}
            onMouseEnter={e => Object.assign(e.currentTarget.style, ghostIconBtnHover)}
            onMouseLeave={e => Object.assign(e.currentTarget.style, {
              ...ghostIconBtnRest, color: 'var(--ms-accent)',
            })}
          >
            <Plus size={14} strokeWidth={2} />
            <span style={{ marginLeft: 1, fontSize: 11 }}>子</span>
          </button>
        </Tooltip>
      )}
    </div>
  );

  if (tree.length === 0) {
    return (
      <div>
        {Header}
        <div style={{ padding: '40px 16px', textAlign: 'center', color: 'var(--ms-ink-subtle)' }}>
          <FolderIcon size={28} strokeWidth={1.4}
                      style={{ color: 'var(--ms-hairline)', marginBottom: 12 }} />
          <div style={{ fontSize: 12.5, lineHeight: 1.6 }}>
            {projectName ?? '项目'}<br/>还没有文件夹
          </div>
          {onCreateRoot && (
            <button
              onClick={onCreateRoot}
              style={{
                marginTop: 16,
                padding: '6px 12px',
                background: 'var(--ms-accent)',
                color: '#fff',
                border: 0,
                borderRadius: 'var(--ms-radius-sm)',
                fontFamily: 'inherit',
                fontSize: 12.5,
                fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              + 新建文件夹
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div>
      {Header}
      <div className="ms-folder-tree" style={{ padding: '6px 4px 12px' }}>
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
    </div>
  );
}

// ─── style consts ────────────────────────────────────────────────────────────
const ghostIconBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  height: 24, minWidth: 24, padding: '0 4px',
  background: 'transparent', border: 0, borderRadius: 'var(--ms-radius-sm)',
  color: 'var(--ms-ink-muted)',
  cursor: 'pointer',
  transition: 'all var(--ms-dur-fast) var(--ms-ease)',
};
const ghostIconBtnHover: React.CSSProperties = {
  background: 'var(--ms-hairline-soft)',
  color: 'var(--ms-ink)',
};
const ghostIconBtnRest: React.CSSProperties = {
  background: 'transparent',
  color: 'var(--ms-ink-muted)',
};
