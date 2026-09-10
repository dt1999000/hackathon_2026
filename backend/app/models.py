import uuid
from datetime import UTC, date, datetime

from pydantic import EmailStr
from sqlalchemy import DateTime, UniqueConstraint
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


# --- SEC EDGAR ingestion (structured facts) ---


# Shared properties
class CompanyBase(SQLModel):
    cik: str = Field(unique=True, index=True, max_length=10)
    name: str = Field(max_length=255)
    ticker: str | None = Field(default=None, max_length=16)
    sic_code: str | None = Field(default=None, max_length=8)


# Database model, database table inferred from class name
class Company(CompanyBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    filings: list[Filing] = Relationship(back_populates="company", cascade_delete=True)


# Properties to return via API, id is always required
class CompanyPublic(CompanyBase):
    id: uuid.UUID
    created_at: datetime | None = None


class CompaniesPublic(SQLModel):
    data: list[CompanyPublic]
    count: int


# Shared properties
class FilingBase(SQLModel):
    accession_number: str = Field(unique=True, index=True, max_length=32)
    form_type: str = Field(max_length=16)
    filing_date: date
    period_of_report: date | None = None
    # Filename of the primary document on SEC's Archives, e.g.
    # "aapl-20260328.htm" — needed to re-fetch the raw filing document for
    # narrative-section extraction without re-hitting submissions.json.
    primary_document: str | None = Field(default=None, max_length=255)


# Database model, database table inferred from class name
class Filing(FilingBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(
        foreign_key="company.id", nullable=False, ondelete="CASCADE", index=True
    )
    # Prior filing of the same form_type for this company, so consecutive
    # filings can be diffed without re-searching for the comparison target.
    previous_filing_id: uuid.UUID | None = Field(
        default=None, foreign_key="filing.id", nullable=True
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    company: Company | None = Relationship(back_populates="filings")
    facts: list[FinancialFact] = Relationship(back_populates="filing", cascade_delete=True)


# Properties to return via API, id is always required
class FilingPublic(FilingBase):
    id: uuid.UUID
    company_id: uuid.UUID
    previous_filing_id: uuid.UUID | None = None
    created_at: datetime | None = None


class FilingsPublic(SQLModel):
    data: list[FilingPublic]
    count: int


# Shared properties
class FinancialFactBase(SQLModel):
    taxonomy: str = Field(max_length=32)
    concept: str = Field(max_length=255, index=True)
    unit: str = Field(max_length=32)
    value: float
    fiscal_year: int | None = None
    fiscal_period: str | None = Field(default=None, max_length=8)
    period_start: date | None = None
    period_end: date | None = None


# Database model, database table inferred from class name
class FinancialFact(FinancialFactBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    filing_id: uuid.UUID = Field(
        foreign_key="filing.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    filing: Filing | None = Relationship(back_populates="facts")


# Properties to return via API, id is always required
class FinancialFactPublic(FinancialFactBase):
    id: uuid.UUID
    filing_id: uuid.UUID
    created_at: datetime | None = None


class FinancialFactsPublic(SQLModel):
    data: list[FinancialFactPublic]
    count: int


# Shared properties
class NarrativeChangeBase(SQLModel):
    section_type: str = Field(max_length=32)  # "risk_factors" | "legal_proceedings"
    change_type: str = Field(max_length=16)  # "new" | "removed" | "modified"
    summary: str
    similarity_score: float | None = None
    new_excerpt: str | None = None
    old_excerpt: str | None = None


# Database model, database table inferred from class name
class NarrativeChange(NarrativeChangeBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    filing_id: uuid.UUID = Field(
        foreign_key="filing.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# Properties to return via API, id is always required
class NarrativeChangePublic(NarrativeChangeBase):
    id: uuid.UUID
    filing_id: uuid.UUID
    created_at: datetime | None = None


class NarrativeChangesPublic(SQLModel):
    data: list[NarrativeChangePublic]
    count: int


# Database model, database table inferred from class name
class Watchlist(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_watchlist_user_company"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True)
    company_id: uuid.UUID = Field(foreign_key="company.id", nullable=False, ondelete="CASCADE", index=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
