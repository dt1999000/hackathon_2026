from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.models import UserCreate
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def random_user_auth_headers(*, client: TestClient, db: Session) -> dict[str, str]:
    """Create a brand-new user (with no company profile yet) and return auth headers for them."""
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password)
    crud.create_user(session=db, user_create=user_in)
    return user_authentication_headers(client=client, email=email, password=password)
