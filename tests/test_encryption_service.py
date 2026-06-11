from app.services.encryption_service import decrypt_value, encrypt_value


def test_encrypt_decrypt_roundtrip():
    plaintext = "super-secret-password"

    ciphertext = encrypt_value(plaintext)

    assert ciphertext != plaintext
    assert decrypt_value(ciphertext) == plaintext
