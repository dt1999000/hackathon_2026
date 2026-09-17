import uuid
from datetime import UTC, date, datetime
from typing import Optional

from pydantic import EmailStr
from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    items: list[Item] = Relationship(back_populates="owner", cascade_delete=True)
    company_profile: Optional["CompanyProfile"] = Relationship(
        back_populates="owner", cascade_delete=True
    )


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


# The string-list fields below are declared as plain `list[str]` (Pydantic-only)
# on the shared Base/Create classes, and re-declared with an explicit Postgres
# ARRAY column only on the table model (CompanyProfile) — same split as
# `created_at`/`sa_type` on User/Item, which also only appears on the table
# class rather than the shared Base.


# Shared properties
class CompanyProfileBase(SQLModel):
    company_name: str = Field(min_length=1, max_length=255)
    base_location: str | None = Field(default=None, max_length=255)
    founded_year: int | None = None
    employee_count: int | None = None
    annual_revenue_eur: float | None = None

    max_radius_km: int | None = None
    served_regions: list[str] = Field(default_factory=list)
    excluded_regions: list[str] = Field(default_factory=list)

    min_contract_value_eur: float | None = None
    max_contract_value_eur: float | None = None
    partner_threshold_eur: float | None = None

    capabilities: list[str] = Field(default_factory=list)
    explicit_exclusions: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)

    contractor_role: str | None = Field(default=None, max_length=32)
    max_self_perform_pct: int | None = None

    guarantee_limit_total_eur: float | None = None
    guarantee_currently_committed_eur: float | None = None

    available_from: date | None = None
    capacity_note: str | None = Field(default=None, max_length=1000)

    reference_projects: list[str] = Field(default_factory=list)
    custom_hardliners: list[str] = Field(default_factory=list)


# Properties to receive via API on creation
class CompanyProfileCreate(CompanyProfileBase):
    pass


# Database model, database table inferred from class name
class CompanyProfile(CompanyProfileBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, unique=True, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="company_profile")

    # Postgres array columns — see the string-list note above CompanyProfileBase.
    served_regions: list[str] = Field(sa_column=Column(ARRAY(String)))
    excluded_regions: list[str] = Field(sa_column=Column(ARRAY(String)))
    capabilities: list[str] = Field(sa_column=Column(ARRAY(String)))
    explicit_exclusions: list[str] = Field(sa_column=Column(ARRAY(String)))
    certifications: list[str] = Field(sa_column=Column(ARRAY(String)))
    reference_projects: list[str] = Field(sa_column=Column(ARRAY(String)))
    custom_hardliners: list[str] = Field(sa_column=Column(ARRAY(String)))


# Properties to return via API, id is always required
class CompanyProfilePublic(CompanyProfileBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
