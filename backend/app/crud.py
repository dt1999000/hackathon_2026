import uuid
from typing import Any

from sqlmodel import Session, select

from app.core.security import get_password_hash, verify_password
from app.models import (
    CompanyProfile,
    CompanyProfileCreate,
    CompanyProfileEmbedding,
    Item,
    ItemCreate,
    User,
    UserCreate,
    UserUpdate,
    get_datetime_utc,
)


def create_user(*, session: Session, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


# Dummy hash to use for timing attack prevention when user is not found
# This is an Argon2 hash of a random password, used to ensure constant-time comparison
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        # Prevent timing attacks by running password verification even when user doesn't exist
        # This ensures the response time is similar whether or not the email exists
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


def create_item(*, session: Session, item_in: ItemCreate, owner_id: uuid.UUID) -> Item:
    db_item = Item.model_validate(item_in, update={"owner_id": owner_id})
    session.add(db_item)
    session.commit()
    session.refresh(db_item)
    return db_item


def create_company_profile(
    *, session: Session, profile_in: CompanyProfileCreate, owner_id: uuid.UUID
) -> CompanyProfile:
    db_profile = CompanyProfile.model_validate(profile_in, update={"owner_id": owner_id})
    session.add(db_profile)
    session.commit()
    session.refresh(db_profile)
    return db_profile


def upsert_company_profile(
    *, session: Session, owner_id: uuid.UUID, profile_in: CompanyProfileCreate
) -> CompanyProfile:
    existing = session.exec(
        select(CompanyProfile).where(CompanyProfile.owner_id == owner_id)
    ).first()
    if existing:
        existing.sqlmodel_update(profile_in.model_dump())
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    return create_company_profile(session=session, profile_in=profile_in, owner_id=owner_id)


def upsert_company_profile_embedding(
    *,
    session: Session,
    company_profile_id: uuid.UUID,
    source_text: str,
    embedding: list[float],
    embedding_model: str,
) -> CompanyProfileEmbedding:
    existing = session.exec(
        select(CompanyProfileEmbedding).where(
            CompanyProfileEmbedding.company_profile_id == company_profile_id
        )
    ).first()
    if existing:
        existing.sqlmodel_update(
            {
                "source_text": source_text,
                "embedding": embedding,
                "embedding_model": embedding_model,
                "updated_at": get_datetime_utc(),
            }
        )
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    db_embedding = CompanyProfileEmbedding(
        company_profile_id=company_profile_id,
        source_text=source_text,
        embedding=embedding,
        embedding_model=embedding_model,
    )
    session.add(db_embedding)
    session.commit()
    session.refresh(db_embedding)
    return db_embedding
