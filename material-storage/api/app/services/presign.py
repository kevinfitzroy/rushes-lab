"""MinIO presigned URL signer + STS — Phase B-2。

双 boto3 client(P-10):
  - s3_internal:容器内访问 MinIO,admin API(create_multipart / complete / abort / list)
  - s3_signer:签 presigned URL 用浏览器视角 host(MINIO_ENDPOINT_PUBLIC)

封装:
  - sign_get_url / sign_put_url
  - 5-endpoint multipart(uppy)
  - issue_sts_for_prefix(7-bis.1 桌面客户端临时凭据)
  - get_object_streaming(敏感目录 FastAPI stream proxy)
"""
from __future__ import annotations

import logging
from typing import Any

import boto3
from botocore.client import Config

from app.settings import Settings

log = logging.getLogger(__name__)


class PresignService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._s3_internal = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint_internal,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            config=Config(signature_version="s3v4", region_name="us-east-1"),
        )
        self._s3_signer = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint_public,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            config=Config(signature_version="s3v4", region_name="us-east-1"),
        )
        self._sts = boto3.client(
            "sts",
            endpoint_url=settings.minio_endpoint_internal,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            region_name="us-east-1",
            config=Config(signature_version="s3v4"),
        )

    def sign_get_url(self, bucket: str, key: str, expires_seconds: int) -> str:
        return self._s3_signer.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    def sign_put_url(self, bucket: str, key: str, expires_seconds: int) -> str:
        return self._s3_signer.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    def create_multipart_upload(
        self, bucket: str, key: str, content_type: str = "application/octet-stream"
    ) -> str:
        resp = self._s3_internal.create_multipart_upload(
            Bucket=bucket, Key=key, ContentType=content_type
        )
        return resp["UploadId"]

    def sign_part_url(
        self, bucket: str, key: str, upload_id: str, part_number: int, expires_seconds: int
    ) -> str:
        return self._s3_signer.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=expires_seconds,
        )

    def complete_multipart_upload(
        self,
        bucket: str,
        key: str,
        upload_id: str,
        parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        resp = self._s3_internal.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )
        return {
            "location": resp.get("Location"),
            "etag": resp.get("ETag"),
            "version_id": resp.get("VersionId"),
        }

    def abort_multipart_upload(self, bucket: str, key: str, upload_id: str) -> None:
        self._s3_internal.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)

    def list_parts(self, bucket: str, key: str, upload_id: str) -> list[dict[str, Any]]:
        resp = self._s3_internal.list_parts(Bucket=bucket, Key=key, UploadId=upload_id)
        return [
            {"PartNumber": p["PartNumber"], "Size": p["Size"], "ETag": p["ETag"]}
            for p in resp.get("Parts", [])
        ]

    def issue_sts_for_prefix(
        self,
        user_id: str,
        bucket: str,
        prefix: str,
        duration_seconds: int = 3600,
        readonly: bool = True,
    ) -> dict[str, str]:
        """7-bis.1:给桌面客户端签 时间 + 资源 双限制 的临时凭据。"""
        actions = ['"s3:GetObject"', '"s3:ListBucket"', '"s3:GetBucketLocation"']
        if not readonly:
            actions += ['"s3:PutObject"', '"s3:AbortMultipartUpload"', '"s3:ListBucketMultipartUploads"']

        policy = f'''{{
            "Version": "2012-10-17",
            "Statement": [
                {{
                    "Effect": "Allow",
                    "Action": [{",".join(actions)}],
                    "Resource": [
                        "arn:aws:s3:::{bucket}",
                        "arn:aws:s3:::{bucket}/{prefix}*"
                    ],
                    "Condition": {{
                        "StringLike": {{"s3:prefix": ["{prefix}*"]}}
                    }}
                }}
            ]
        }}'''
        resp = self._sts.assume_role(
            RoleArn=f"arn:minio:sts::{user_id}",
            RoleSessionName=f"material-storage-{user_id}",
            DurationSeconds=duration_seconds,
            Policy=policy,
        )
        creds = resp["Credentials"]
        return {
            "access_key": creds["AccessKeyId"],
            "secret_key": creds["SecretAccessKey"],
            "session_token": creds["SessionToken"],
            "expiration": creds["Expiration"].isoformat(),
        }

    def get_object_streaming(self, bucket: str, key: str):  # type: ignore[no-untyped-def]
        """敏感目录代理 stream 用;返回 StreamingBody,可 iter_chunks()。"""
        resp = self._s3_internal.get_object(Bucket=bucket, Key=key)
        return resp["Body"]
