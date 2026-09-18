import uuid
from datetime import UTC, datetime
from typing import Optional

from pydantic import EmailStr
from sqlalchemy import DateTime, Text
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


# Deliberately minimal set of typed fields — see the note above each
# free-text field below for why the rest aren't numeric/enum/array
# columns. No Postgres ARRAY columns are needed anymore, so the table
# model doesn't re-declare anything beyond CompanyProfileBase.


# Shared properties
class CompanyProfileBase(SQLModel):
    # Basic, objective facts — no business-rule nuance, safe as plain
    # typed fields.
    company_name: str = Field(min_length=1, max_length=255)
    base_location: str | None = Field(default=None, max_length=255)
    founded_year: int | None = None
    employee_count: int | None = None
    annual_revenue_eur: float | None = None

    # Everything else is free text, one field per topic, instead of
    # narrow numeric/enum/array fields (e.g. a bare partner_threshold_eur
    # number can't express "we can bring in a partner if the value is a
    # bit over our usual ceiling" — the company's own words can). Each
    # field is both (a) embedded independently for bid-similarity
    # matching (app.agents.bid_fit.derive_profile_sections) and (b)
    # passed as context to the LLM that reasons about hardliner
    # violations and solutions (app.agents.bid_fit.generate_violations),
    # which can work with that nuance directly instead of it being lost
    # to a rigid pre-computed rule.
    geographic_reach: str | None = Field(default=None, max_length=1000)
    contract_size: str | None = Field(default=None, max_length=1000)
    capabilities: str | None = Field(default=None, max_length=1000)
    exclusions: str | None = Field(default=None, max_length=1000)
    certifications: str | None = Field(default=None, max_length=1000)
    contractor_role: str | None = Field(default=None, max_length=500)
    capacity: str | None = Field(default=None, max_length=1000)
    reference_projects: str | None = Field(default=None, max_length=1000)
    # One hardliner/exclusion per line — see
    # app.agents.bid_fit.derive_hardliners_from_profile.
    hardliners: str | None = Field(default=None, max_length=1000)

    self_description: str | None = Field(default=None, max_length=2000)


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


# Properties to return via API, id is always required
class CompanyProfilePublic(CompanyProfileBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


# A tender notice loaded from mock_data/bids/*.json (see app.seed_bids),
# in this app's "contract notice" schema — see
# app.agents.bid_fit._extract_bid_notice_text, which reads raw_json back
# out for the bid-fit pipeline. Not owner-scoped: bids are a shared pool
# every user's dashboard analyzes against their own company profile.
class BidBase(SQLModel):
    source_file: str = Field(max_length=255, unique=True)
    title: str | None = Field(default=None, max_length=1000)
    notice_identifier: str | None = Field(default=None, max_length=100)
    place_of_performance: str | None = Field(default=None, max_length=500)


class Bid(BidBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    # The full parsed bid-notice JSON, verbatim — fed back in as
    # bid_content to run_bid_fit_analysis (bid_loader="json").
    raw_json: str = Field(sa_type=Text)


class BidPublic(BidBase):
    id: uuid.UUID
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


# --- Contract table: one row per (notice, lot) from the tender-matching --
# --- pipeline (ted_pipeline.py -> contract_schema.json instances). ------

from sqlalchemy import JSON, Text, UniqueConstraint  # noqa: E402


class Contract(SQLModel, table=True):
    """One row per (notice, lot). See ted_pipeline.py / contract_schema.json:
    notice.identifier + notice.version + notice.lotIdentifier together are
    the natural key -- a notice can have multiple lots, and each lot gets
    its own row here. notice_version/lot_identifier are stored as "" rather
    than NULL specifically so the unique constraint below actually holds --
    Postgres treats every NULL as distinct, so two NULLs would NOT collide
    and the constraint would silently stop catching duplicates.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    source_system: str
    source_record_id: str

    notice_identifier: str = Field(index=True)
    notice_version: str = Field(default="")
    lot_identifier: str = Field(default="")

    publication_date: str | None = None
    buyer_names: list = Field(default_factory=list, sa_type=JSON)
    procedure_title: str | None = Field(default=None, sa_type=Text)

    main_nature: str | None = None
    main_cpv_code: str | None = None
    additional_cpv_codes: list = Field(default_factory=list, sa_type=JSON)

    place_of_performance: list = Field(default_factory=list, sa_type=JSON)

    estimated_value: float | None = None
    currency: str | None = None

    deadline_date: str | None = None
    deadline_time: str | None = None

    procurement_document_links: list = Field(default_factory=list, sa_type=JSON)

    # documentContents in contract_schema.json is an array (TED: one entry,
    # the notice PDF; oeffentlichevergabe.de: one per real downloaded
    # attachment). Kept structured here so sourceUrl/fileName/needsOcr
    # aren't thrown away, plus a flattened plain-text column for anyone who
    # just wants to grep/full-text-search the content without unpacking JSON.
    document_contents: list = Field(default_factory=list, sa_type=JSON)
    document_contents_text: str | None = Field(default=None, sa_type=Text)

    # Set by dedupe_contracts.py when the same real tender was found in both
    # sources; None if this record was never part of a detected duplicate
    # group. duplicate_role is "primary" (keep) or "secondary" (the same
    # contract, counted once already via its primary copy).
    duplicate_group_id: str | None = Field(default=None, index=True)
    duplicate_role: str | None = None

    raw_json: dict = Field(default_factory=dict, sa_type=JSON)  # full instance, for safekeeping

    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )

    __table_args__ = (
        UniqueConstraint(
            "notice_identifier", "notice_version", "lot_identifier",
            name="uq_contract_notice_version_lot",
        ),
    )