"""Cloudflare R2 storage — upload de imagens e URLs públicas."""

import os
import tempfile
from pathlib import Path
from typing import Optional

import requests

R2_ACCOUNT_ID  = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY  = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_KEY  = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET      = os.getenv("R2_BUCKET_NAME", "cognivita-imagens")
R2_PUBLIC_URL  = os.getenv("R2_PUBLIC_URL", "")  # ex: https://pub-xxx.r2.dev


def _configured() -> bool:
    return bool(R2_ACCOUNT_ID and R2_ACCESS_KEY and R2_SECRET_KEY)


def _client():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def upload(local_path: str, key: Optional[str] = None) -> str:
    """
    Faz upload de arquivo local para R2 e retorna a URL pública.
    Se R2 não estiver configurado, retorna o caminho local sem erro.
    """
    if not _configured():
        return local_path

    if not local_path or not Path(local_path).exists():
        return local_path

    if key is None:
        key = Path(local_path).name

    _client().upload_file(
        local_path,
        R2_BUCKET,
        key,
        ExtraArgs={"ContentType": "image/png"},
    )

    if R2_PUBLIC_URL:
        return f"{R2_PUBLIC_URL.rstrip('/')}/{key}"
    return f"https://{R2_BUCKET}.{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/{key}"


def is_url(path: str) -> bool:
    return bool(path and path.startswith("http"))


def download_to_temp(url: str) -> str:
    """Baixa URL para arquivo temporário e retorna o caminho local."""
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    suffix = ".png" if "png" in url.lower() else ".jpg"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(r.content)
    tmp.close()
    return tmp.name
