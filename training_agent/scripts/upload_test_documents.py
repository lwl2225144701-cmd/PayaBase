import json
import mimetypes
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from models.tables import KnowledgeBase


BASE_URL = os.getenv("TRAINING_AGENT_BASE_URL", "http://127.0.0.1:8123")
LOGIN_CODE = os.getenv("TRAINING_AGENT_LOGIN_CODE", "admin")
DOC_DIR = Path(__file__).parent / "test_seed_docs"

DOC_MAPPING = {
    "研发知识库": DOC_DIR / "rd_api_spec.md",
    "销售知识库": DOC_DIR / "sales_playbook.md",
    "人事知识库": DOC_DIR / "hr_policy.md",
}


def request_json(url: str, method: str = "GET", headers: dict | None = None, data: bytes | None = None) -> dict:
    req = urllib.request.Request(url=url, method=method, headers=headers or {}, data=data)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def login(code: str) -> str:
    url = f"{BASE_URL}/api/auth/sso?{urllib.parse.urlencode({'code': code})}"
    payload = request_json(url, method="POST")
    return payload["data"]["access_token"]


def encode_multipart(fields: dict[str, str], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = f"----CodexBoundary{int(time.time() * 1000)}"
    body = bytearray()

    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    for field_name, file_path in files:
        filename = file_path.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
        body.extend(file_path.read_bytes())
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), boundary


def get_kbs() -> list[KnowledgeBase]:
    engine = create_engine(settings.sync_database_url)
    with Session(engine) as db:
        return list(
            db.scalars(
                select(KnowledgeBase).where(KnowledgeBase.name.in_(list(DOC_MAPPING.keys())))
            ).all()
        )


def upload_document(token: str, kb_id: str, file_path: Path) -> dict:
    body, boundary = encode_multipart({}, [("file", file_path)])
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    url = f"{BASE_URL}/api/kb/{kb_id}/docs"
    return request_json(url, method="POST", headers=headers, data=body)


def poll_status(token: str, kb_id: str, doc_id: str, timeout_seconds: int = 180) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.time() + timeout_seconds
    url = f"{BASE_URL}/api/kb/{kb_id}/docs/{doc_id}/indexing-status"
    while time.time() < deadline:
        result = request_json(url, headers=headers)
        data = result["data"]
        status = data["status"]
        if status == "ready":
            return data
        if status in {"failed", "error"}:
            raise RuntimeError(f"文档索引失败: {data}")
        time.sleep(2)
    raise TimeoutError(f"文档索引超时: kb_id={kb_id}, doc_id={doc_id}")


def main() -> None:
    token = login(LOGIN_CODE)
    kbs = get_kbs()
    if not kbs:
        raise RuntimeError("未找到测试知识库，请先执行 init_test_data.py")

    print(f"开始上传测试文档，base_url={BASE_URL}，login_code={LOGIN_CODE}")
    for kb in kbs:
        file_path = DOC_MAPPING.get(kb.name)
        if not file_path or not file_path.exists():
            raise FileNotFoundError(f"缺少测试文档: {kb.name}")
        result = upload_document(token, str(kb.id), file_path)
        doc = result["data"]
        print(f"已提交上传: kb={kb.name} doc={doc['title']} id={doc['id']} status={doc['status']}")
        status = poll_status(token, str(kb.id), doc["id"])
        print(f"索引完成: kb={kb.name} progress={status['progress']} chunks={status['chunk_count']}")

    print("全部测试文档上传并索引完成")


if __name__ == "__main__":
    main()
