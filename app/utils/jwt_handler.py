import jwt
import os
import logging
from fastapi import HTTPException
from typing import Dict

logger = logging.getLogger(__name__)

class JWTHandler:
    def __init__(self, secret_key: str = None, algorithm: str = "HS256"):
        """
        Initialize JWTHandler with a secret key and algorithm.

        Args:
            secret_key (str, optional): Secret key for signing/verifying JWT. Defaults to JWT_SECRET_KEY env variable.
            algorithm (str, optional): Algorithm for JWT (e.g., HS256). Defaults to HS256.

        Raises:
            ValueError: If secret_key is not provided and JWT_SECRET_KEY is not set.
        """
        self.secret_key = secret_key or os.getenv("JWT_SECRET_KEY")
        if not self.secret_key:
            raise ValueError("JWT_SECRET_KEY must be set in environment variables")
        self.algorithm = algorithm


    def verify_jwt(self, token: str) -> Dict:
        """
        Verify a JWT token and return its payload.

        Args:
            token (str): JWT token to verify.

        Returns:
            Dict: Decoded payload of the token.

        Raises:
            HTTPException: If the token is invalid, expired, or malformed.
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning(f"Token expired: {token[:10]}...")
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {str(e)}")
            raise HTTPException(status_code=401, detail="Invalid token")
        except Exception as e:
            logger.error(f"Unexpected error verifying token: {str(e)}")
            raise HTTPException(status_code=401, detail="Token verification failed")