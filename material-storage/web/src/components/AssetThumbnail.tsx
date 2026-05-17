/**
 * AssetThumbnail — 拿 asset.tags.thumbnail_key 签 presigned URL 显示 img。
 * 无缩略图 / 非图 / 失败 → fallback 文件图标。
 * 32×32 size,可配。
 */
import { FileText } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { http } from '../api/client';
import type { Asset } from '../api/types';

interface Props {
  asset: Asset;
  size?: number;
}

export function AssetThumbnail({ asset, size = 32 }: Props) {
  const hasThumb = !!asset.tags?.thumbnail_key;
  const [imgError, setImgError] = useState(false);

  const { data } = useQuery({
    queryKey: ['thumbnail-url', asset.id],
    queryFn: async () =>
      (await http.get<{ url: string; expires_in: number }>(
        `/api/v1/assets/${asset.id}/thumbnail-url`,
      )).data,
    enabled: hasThumb && !imgError,
    staleTime: 25 * 60 * 1000,   // 25 min(presigned 30 min,留余量)
    retry: false,
  });

  const boxStyle: React.CSSProperties = {
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    width: size, height: size, flexShrink: 0,
    background: 'var(--ms-hairline-soft)',
    borderRadius: 'var(--ms-radius-sm)',
    color: 'var(--ms-ink-subtle)',
    overflow: 'hidden',
  };

  if (hasThumb && data?.url && !imgError) {
    return (
      <span style={boxStyle}>
        <img
          src={data.url}
          alt=""
          width={size} height={size}
          loading="lazy"
          onError={() => setImgError(true)}
          style={{
            width: '100%', height: '100%',
            objectFit: 'cover',
            display: 'block',
          }}
        />
      </span>
    );
  }

  return (
    <span style={boxStyle}>
      <FileText size={size === 32 ? 14 : Math.round(size * 0.45)} strokeWidth={1.5} />
    </span>
  );
}
