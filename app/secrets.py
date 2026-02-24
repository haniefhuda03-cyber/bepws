import os
from typing import Optional


def get_secret(name: str) -> Optional[str]:
    v = os.environ.get(name)
    if v:
        return v
    secrets_dir = os.environ.get('SECRETS_DIR')
    if secrets_dir:
        p = os.path.join(secrets_dir, name)
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except Exception:
                return None
    return None