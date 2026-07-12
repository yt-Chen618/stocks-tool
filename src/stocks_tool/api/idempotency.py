import re
from typing import Annotated

from fastapi import Header, HTTPException


IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,128}$", re.ASCII)


def require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if idempotency_key is None:
        raise HTTPException(
            status_code=428,
            detail={
                "code": "idempotency_key_required",
                "message": "Idempotency-Key header is required for broker mutations.",
                "retryable": True,
            },
        )
    if IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key) is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "idempotency_key_invalid",
                "message": (
                    "Idempotency-Key must be 16-128 ASCII characters using "
                    "letters, digits, '.', '_', ':', or '-'."
                ),
                "retryable": True,
            },
        )
    return idempotency_key
