# """
# Authentication service with JWT tokens
# """
# from datetime import datetime, timedelta
# from typing import Optional
# from jose import JWTError, jwt
# from passlib.context import CryptContext
# from fastapi import Depends, HTTPException, status
# from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select

# from config.settings import get_settings
# from database.connection import get_db
# from database_models.postgres_model import User
# import bcrypt

# settings = get_settings()
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# security = HTTPBearer()


# class AuthService:
#     """Authentication service for user management"""

#     @staticmethod

#     def hash_password(password: str):
#         password_bytes = password.encode('utf-8')

#         if len(password_bytes) > 72:
#             raise ValueError("Password too long (max 72 bytes)")

#         hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
#         return hashed.decode('utf-8')
#     # def hash_password(password: str) -> str:
#     #     """Hash a password"""
#     #     return pwd_context.hash(password)
    
#     @staticmethod
    
#     def verify_password(plain_password, password_hash):
#         return bcrypt.checkpw(
#             plain_password.encode('utf-8'),
#             password_hash.encode('utf-8')
#         )
#         # @staticmethod
#     # def verify_password(plain_password: str, password_hash: str) -> bool:
#     #     """Verify a password against a hash"""
#     #     return pwd_context.verify(plain_password, password_hash)
    
#     @staticmethod
#     def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
#         """Create JWT access token"""
#         to_encode = data.copy()
        
#         if expires_delta:
#             expire = datetime.utcnow() + expires_delta
#         else:
#             expire = datetime.utcnow() + timedelta(
#                 minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
#             )
        
#         to_encode.update({"exp": expire})
#         encoded_jwt = jwt.encode(
#             to_encode,
#             settings.SECRET_KEY,
#             algorithm=settings.ALGORITHM
#         )
        
#         return encoded_jwt
    
#     @staticmethod
#     async def authenticate_user(
#         db: AsyncSession,
#         username: str,
#         password: str
#     ) -> Optional[User]:
#         """Authenticate user by username and password"""
#         result = await db.execute(
#             select(User).where(User.username == username)
#         )
#         user = result.scalar_one_or_none()
        
#         if not user:
#             return None
#         if not AuthService.verify_password(password, user.password_hash):
#             return None
        
#         return user
    
#     @staticmethod
#     async def get_current_user(
#         credentials: HTTPAuthorizationCredentials = Depends(security),
#         db: AsyncSession = Depends(get_db)
#     ) -> User:
#         """Get current authenticated user from JWT token"""
#         credentials_exception = HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Could not validate credentials",
#             headers={"WWW-Authenticate": "Bearer"},
#         )
        
#         try:
#             token = credentials.credentials
#             payload = jwt.decode(
#                 token,
#                 settings.SECRET_KEY,
#                 algorithms=[settings.ALGORITHM]
#             )
#             username: str = payload.get("sub")
            
#             if username is None:
#                 raise credentials_exception
                
#         except JWTError:
#             raise credentials_exception
        
#         result = await db.execute(
#             select(User).where(User.username == username)
#         )
#         user = result.scalar_one_or_none()
        
#         if user is None:
#             raise credentials_exception
        
#         if not user.is_active:
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="Inactive user"
#             )
        
#         # Update last login
#         user.last_login = datetime.now()
#         await db.commit()
        
#         return user


# # Dependency for protected routes
# async def get_current_active_user(
#     current_user: User = Depends(AuthService.get_current_user)
# ) -> User:
#     """Dependency to get current active user"""
#     if not current_user.is_active:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Inactive user"
#         )
#     return current_user
"""
Authentication service with JWT tokens
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config.settings import get_settings
from database.connection import get_db
from database_models.postgres_model import User
import bcrypt

settings = get_settings()
security = HTTPBearer()


class AuthService:
    """Authentication service for user management"""

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt"""
        password_bytes = password.encode('utf-8')
        if len(password_bytes) > 72:
            raise ValueError("Password too long (max 72 bytes)")
        hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
        return hashed.decode('utf-8')

    @staticmethod
    def verify_password(plain_password: str, password_hash: str) -> bool:
        """Verify a password against its hash"""
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            password_hash.encode('utf-8')
        )

    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create JWT access token"""
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(
                minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
            )

        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(
            to_encode,
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM
        )
        return encoded_jwt

    @staticmethod
    async def authenticate_user(
        db: AsyncSession,
        username: str,
        password: str
    ) -> Optional[User]:
        """Authenticate user by username and password"""
        result = await db.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()

        if not user:
            return None

        # ✅ Fixed: use password_hash (matches the field name set during registration)
        if not AuthService.verify_password(password, user.password_hash):
            return None

        return user

    @staticmethod
    async def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: AsyncSession = Depends(get_db)
    ) -> User:
        """Get current authenticated user from JWT token"""
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

        try:
            token = credentials.credentials
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM]
            )
            username: str = payload.get("sub")

            if username is None:
                raise credentials_exception

        except JWTError:
            raise credentials_exception

        result = await db.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise credentials_exception

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inactive user"
            )

        # Update last login
        user.last_login = datetime.now()
        await db.commit()

        return user


# Dependency for protected routes
async def get_current_active_user(
    current_user: User = Depends(AuthService.get_current_user)
) -> User:
    """Dependency to get current active user"""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    return current_user