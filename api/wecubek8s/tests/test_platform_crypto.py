from wecubek8s.common.utils import platform_decrypt, platform_encrypt


def test_platform_encrypt_returns_ciphertext_that_can_be_decrypted():
    ciphertext = platform_encrypt('sample-value', 'sample-guid', 'sample-seed')

    assert ciphertext == '{cipher_a}2a537b600dec3d4da3af86b8e4232368'
    assert platform_decrypt(ciphertext, 'sample-guid', 'sample-seed') == 'sample-value'


def test_platform_decrypt_reads_existing_ciphertext():
    ciphertext = '{cipher_a}2a537b600dec3d4da3af86b8e4232368'

    assert platform_decrypt(ciphertext, 'sample-guid', 'sample-seed') == 'sample-value'
