"""permissions service stub — Phase B-1 placeholder。

实施引用:
- permissions: openfga-sdk wrapper(grant / check / revoke)— ADR-0006 §1 + PoC openfga/
- presign:    boto3 generate_presigned_url + 双 client 模式(P-10)
- proxy:      敏感目录 FastAPI stream + 每 chunk OpenFGA check(Gap 1 + Gap 3)
- audit:      audit-schema 修订版(PR #30 + ADR-0005 §11.2 Gap 10)
- feishu:     larksuite/oapi-sdk-python 调用 + bridge webhook handler
"""
