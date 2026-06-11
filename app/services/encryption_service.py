from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class DecryptionError(ValueError):
    pass


def _fernet() -> Fernet:
    return Fernet(settings.CONNECTOR_ENCRYPTION_KEY.encode())


def encrypt_value(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError("Could not decrypt value with the configured key") from exc
