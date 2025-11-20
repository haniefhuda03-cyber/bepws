import os
from typing import Optional

SECRETS_DIR = os.environ.get('SECRETS_DIR')


def get_secret(name: str) -> Optional[str]:
    v = os.environ.get(name)
    if v:
        return v
    if SECRETS_DIR:
        p = os.path.join(SECRETS_DIR, name)
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except Exception:
                return None
    return None