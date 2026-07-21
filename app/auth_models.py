from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.models import ApiModel


UserRole = Literal["admin", "operator", "driver"]


class BootstrapAdminRequest(ApiModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=10, max_length=256)
    display_name: str = Field(min_length=1, max_length=100)


class CreateUserRequest(BootstrapAdminRequest):
    role: UserRole
    driver_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def driver_role_requires_driver_id(self) -> "CreateUserRequest":
        if self.role == "driver" and not self.driver_id:
            raise ValueError("driver role requires driver_id")
        if self.role != "driver" and self.driver_id:
            raise ValueError("only driver role can have driver_id")
        return self


class LoginRequest(ApiModel):
    username: str
    password: str
    device_id: str | None = Field(default=None, max_length=200)


class RefreshTokenRequest(ApiModel):
    refresh_token: str


class LogoutRequest(RefreshTokenRequest):
    pass


class UserResponse(ApiModel):
    user_id: str
    username: str
    display_name: str
    role: UserRole
    driver_id: str | None = None
    is_active: bool
    created_at: datetime


class AuthTokens(ApiModel):
    token_type: Literal["bearer"] = "bearer"
    access_token: str
    access_expires_in_seconds: int
    refresh_token: str
    refresh_expires_in_seconds: int
    user: UserResponse


class AuthPrincipal(ApiModel):
    user_id: str
    username: str
    display_name: str
    role: UserRole
    driver_id: str | None = None

