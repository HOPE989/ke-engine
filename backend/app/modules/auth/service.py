from app.core.security import get_password_hash, verify_password


class AuthService:
    def hash_password(self, password: str) -> str:
        return get_password_hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return verify_password(plain_password, hashed_password)

