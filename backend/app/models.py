import uuid
from datetime import UTC, datetime

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
    # Quoted as forward references: Item and Profile are defined further
    # down this file, and Python evaluates a class-body annotation's
    # expression immediately (there's no `from __future__ import
    # annotations` here), so an unquoted `list[Item]` at this point would
    # raise NameError -- the quotes defer resolution to SQLModel's
    # model_rebuild() once every class in the file exists. Ruff's UP037
    # ("remove quotes from type annotation") doesn't know that and would
    # reintroduce the crash, so it's silenced on these two lines only.
    items: list["Item"] = Relationship(  # noqa: UP037
        back_populates="owner", cascade_delete=True
    )
    profiles: list["Profile"] = Relationship(  # noqa: UP037
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


# --- Profile: a company profile used to match the firm against tenders. ---
# Replaces the old Items tab in the UI. Every field is optional by design --
# a contractor can fill this in incrementally, and the matching pipeline
# should work with whatever subset is on file rather than demand a
# complete profile up front.


# Shared properties
class ProfileBase(SQLModel):
    company_name: str | None = Field(default=None, max_length=255)
    base_location: str | None = Field(default=None, max_length=255)
    founded_year: int | None = None
    employee_count: int | None = None
    annual_revenue_eur: int | None = None
    # Free-text fields below often hold multi-sentence descriptions (and in
    # the case of exclusions/hardliners, embedded newlines), so they're
    # stored as unbounded Text rather than a short varchar.
    geographic_reach: str | None = Field(default=None, sa_type=Text)
    contract_size: str | None = Field(default=None, sa_type=Text)
    capabilities: str | None = Field(default=None, sa_type=Text)
    exclusions: str | None = Field(default=None, sa_type=Text)
    certifications: str | None = Field(default=None, sa_type=Text)
    contractor_role: str | None = Field(default=None, max_length=255)
    capacity: str | None = Field(default=None, sa_type=Text)
    reference_projects: str | None = Field(default=None, sa_type=Text)
    hardliners: str | None = Field(default=None, sa_type=Text)
    self_description: str | None = Field(default=None, sa_type=Text)


# Properties to receive on profile creation -- all optional, same as above
class ProfileCreate(ProfileBase):
    pass


# Properties to receive on profile update -- all optional
class ProfileUpdate(ProfileBase):
    pass


# Database model, database table inferred from class name
class Profile(ProfileBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="profiles")


# Properties to return via API, id is always required
class ProfilePublic(ProfileBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ProfilesPublic(SQLModel):
    data: list[ProfilePublic]
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


# --- Contract table: one row per (notice, lot) from the tender-matching --
# --- pipeline (ted_pipeline.py -> contract_schema.json instances). ------

from sqlalchemy import JSON, UniqueConstraint  # noqa: E402


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


# --- Dashboard: pin state + refresh tracking for the bids table. ----------
# Kept as their own tables (not new columns on Contract) so the crawl/import
# pipelines (ted_pipeline.py, CPV45_Eforms_Attachments_Pipeline.py,
# build_schema_from_agent_input.py, dedupe_contracts.py,
# run_contract_pipelines.py, scripts/import_contracts.py) never need to
# know about them -- upserting a Contract row never touches these.


class BidPin(SQLModel, table=True):
    """Whether a bid (Contract row) is pinned to the top of the Dashboard.
    One row per pinned contract; unpinning deletes the row. Pin state is
    shared across everyone viewing the Dashboard (not per-user), matching
    the rest of the Contract table, which has no owner concept either."""

    contract_id: uuid.UUID = Field(
        foreign_key="contract.id", primary_key=True, ondelete="CASCADE"
    )
    pinned_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)  # type: ignore
    )


class DashboardRefreshState(SQLModel, table=True):
    """Singleton row (id is always 1) tracking the Dashboard's Refresh
    button: whether a refresh is currently running, when the last one
    finished, how many new bids it found, and the cutoff timestamp used to
    flag a Contract as "New!" in the UI.

    new_since_at semantics: any Contract.created_at strictly after
    new_since_at is considered new. import_contracts.py's upsert only sets
    created_at when a row is first inserted (see Contract above), so this
    stays correct across reruns that just update existing rows. Each
    completed refresh advances new_since_at to that refresh's own start
    time, so bids found by the refresh that just finished stay flagged
    "New!" until the *next* refresh completes.
    """

    id: int = Field(default=1, primary_key=True)
    status: str = Field(default="idle")  # "idle" | "running" | "error"
    started_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)  # type: ignore
    )
    last_refreshed_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)  # type: ignore
    )
    new_since_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)  # type: ignore
    )
    last_new_count: int = Field(default=0)
    last_error: str | None = Field(default=None, sa_type=Text)
