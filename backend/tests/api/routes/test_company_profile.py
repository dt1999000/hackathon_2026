from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from tests.utils.company_profile import random_user_auth_headers


def test_create_company_profile(client: TestClient, db: Session) -> None:
    headers = random_user_auth_headers(client=client, db=db)
    data = {
        "company_name": "Brenner & Sohn Tiefbau GmbH",
        "base_location": "Augsburg, Bavaria",
        "geographic_reach": "Bavaria, mainly Schwaben and Oberbayern, up to ~150 km from Augsburg",
        "capabilities": "road construction, sewers and pipelines",
        "hardliners": "No rail-side work\nNothing outside Germany",
    }
    response = client.post(
        f"{settings.API_V1_STR}/company-profile/me", headers=headers, json=data
    )
    assert response.status_code == 200
    content = response.json()
    assert content["company_name"] == data["company_name"]
    assert content["base_location"] == data["base_location"]
    assert content["capabilities"] == data["capabilities"]
    assert content["hardliners"] == data["hardliners"]
    assert "id" in content
    assert "owner_id" in content


def test_create_company_profile_duplicate(client: TestClient, db: Session) -> None:
    headers = random_user_auth_headers(client=client, db=db)
    data = {"company_name": "Elektro Vogtland GmbH"}
    first = client.post(
        f"{settings.API_V1_STR}/company-profile/me", headers=headers, json=data
    )
    assert first.status_code == 200

    second = client.post(
        f"{settings.API_V1_STR}/company-profile/me", headers=headers, json=data
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "Company profile already exists"


def test_read_company_profile_me(client: TestClient, db: Session) -> None:
    headers = random_user_auth_headers(client=client, db=db)
    data = {"company_name": "Hanseatische Bau AG"}
    client.post(f"{settings.API_V1_STR}/company-profile/me", headers=headers, json=data)

    response = client.get(f"{settings.API_V1_STR}/company-profile/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["company_name"] == data["company_name"]


def test_read_company_profile_me_not_found(client: TestClient, db: Session) -> None:
    headers = random_user_auth_headers(client=client, db=db)
    response = client.get(f"{settings.API_V1_STR}/company-profile/me", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Company profile not found"


def test_read_company_profile_me_unauthenticated(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/company-profile/me")
    assert response.status_code == 401


def test_create_company_profile_unauthenticated(client: TestClient) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/company-profile/me",
        json={"company_name": "Unauthenticated Co"},
    )
    assert response.status_code == 401
