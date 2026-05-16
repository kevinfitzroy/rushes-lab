import { Breadcrumb } from 'antd';
import { HomeOutlined, FolderOutlined, ProjectOutlined } from '@ant-design/icons';
import { Link, useLocation, useParams } from 'react-router-dom';
import { useFolder, useProject } from '../api/hooks';

/** 根据当前路由自动渲染面包屑 — 项目/文件夹页。*/
export function AppBreadcrumb() {
  const location = useLocation();
  const { projectId, folderId } = useParams<{ projectId?: string; folderId?: string }>();

  // folder 页时回查 folder → project 关联
  const { data: folder } = useFolder(folderId);
  const effectiveProjectId = projectId ?? folder?.project_id;
  const { data: project } = useProject(effectiveProjectId);

  const items: { title: React.ReactNode }[] = [
    { title: <Link to="/"><HomeOutlined /> 项目</Link> },
  ];

  if (location.pathname.startsWith('/projects/') && project) {
    items.push({ title: <><ProjectOutlined /> {project.name}</> });
  } else if (location.pathname.startsWith('/folders/') && folder) {
    if (project) {
      items.push({ title: <Link to={`/projects/${project.id}`}><ProjectOutlined /> {project.name}</Link> });
    }
    items.push({ title: <><FolderOutlined /> {folder.name}</> });
  } else if (location.pathname.startsWith('/approvals')) {
    items.push({ title: '审批' });
  }

  if (items.length <= 1) return null;
  return <Breadcrumb items={items} style={{ marginBottom: 16 }} />;
}
