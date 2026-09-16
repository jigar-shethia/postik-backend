"""
End-to-End Automated Test Suite & Attack Simulation
===================================================
This module contains comprehensive integration tests covering happy paths,
edge cases, and security attack simulations (replay attacks, brute-force locks,
rate limiting, and token theft detection).

Beginner Concepts:
------------------
1. **Mocking Deterministic Values (`unittest.mock.patch`)**:
   In production, OTPs are random 6-digit numbers. In tests, we patch `generate_otp`
   to return a fixed string (e.g. `"123456"`) so our tests are 100% deterministic and reliable.

2. **Attack Simulations**:
   - **Replay Attack**: Trying to reuse a consumed one-time registration token.
   - **Brute-Force Attack**: Sending rapid wrong OTP guesses until lockout.
   - **Token Theft / Rotation Reuse**: Using an old refresh token to trigger session revocation.
"""

from unittest.mock import patch
import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_health_endpoints(client: AsyncClient):
    """
    Verifies that /health and /api/v1/health endpoints return HTTP 200 with service statuses.
    """
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["app_name"] == "Postik API"
    assert "services" in data


@pytest.mark.asyncio
async def test_full_new_user_signup_flow(client: AsyncClient):
    """
    Simulates complete onboarding flow for a brand new user:
    1. POST /auth/otp/send
    2. POST /auth/otp/verify -> returns is_new_user: true and registration_token
    3. POST /auth/register -> returns access_token and user profile
    4. GET /auth/me -> retrieves profile using access_token
    """
    phone = "+14155552671"

    with patch("app.services.sms.dispatcher.generate_otp", return_value="123456"):
        # 1. Send OTP
        send_res = await client.post("/api/v1/auth/otp/send", json={"phone": phone})
        assert send_res.status_code == 200
        assert send_res.json()["retry_in_seconds"] == 60

        # 2. Verify OTP
        verify_res = await client.post(
            "/api/v1/auth/otp/verify", json={"phone": phone, "otp": "123456"}
        )
        assert verify_res.status_code == 200
        verify_data = verify_res.json()
        assert verify_data["is_new_user"] is True
        assert "registration_token" in verify_data
        reg_token = verify_data["registration_token"]

        # 3. Register Customer Profile
        reg_res = await client.post(
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {reg_token}"},
            json={"name": "Alice Johnson", "email": "alice@example.com"},
        )
        assert reg_res.status_code == 201
        reg_data = reg_res.json()
        assert "access_token" in reg_data
        assert "refresh_token" in reg_data
        assert reg_data["user"]["name"] == "Alice Johnson"
        assert reg_data["user"]["phone"] == phone
        access_token = reg_data["access_token"]

        # 4. Authenticated Request to /auth/me
        me_res = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_res.status_code == 200
        assert me_res.json()["name"] == "Alice Johnson"


@pytest.mark.asyncio
async def test_existing_user_login(client: AsyncClient, test_redis: Redis):
    """
    Verifies that an already-registered user logs in directly upon OTP verification.
    """
    phone = "+14155559999"

    # Onboard the user first
    with patch("app.services.sms.dispatcher.generate_otp", return_value="111111"):
        await client.post("/api/v1/auth/otp/send", json={"phone": phone})
        v_res = await client.post(
            "/api/v1/auth/otp/verify", json={"phone": phone, "otp": "111111"}
        )
        reg_token = v_res.json()["registration_token"]
        await client.post(
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {reg_token}"},
            json={"name": "Bob Smith"},
        )

    # Now simulate a subsequent login (clear cooldown key so second send is permitted)
    await test_redis.delete(f"cooldown:otp:{phone}")
    with patch("app.services.sms.dispatcher.generate_otp", return_value="222222"):
        # Send OTP
        send_res = await client.post("/api/v1/auth/otp/send", json={"phone": phone})
        assert send_res.status_code == 200

        # Verify OTP -> Should log in directly
        login_res = await client.post(
            "/api/v1/auth/otp/verify", json={"phone": phone, "otp": "222222"}
        )
        assert login_res.status_code == 200
        login_data = login_res.json()
        assert login_data["is_new_user"] is False
        assert "access_token" in login_data
        assert "refresh_token" in login_data

        # Verify access token works
        me_res = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {login_data['access_token']}"},
        )
        assert me_res.status_code == 200
        assert me_res.json()["name"] == "Bob Smith"


@pytest.mark.asyncio
async def test_cooldown_enforcement(client: AsyncClient):
    """
    Simulates sending two OTP requests within 60 seconds; second request must return HTTP 429.
    """
    phone = "+14155553333"

    with patch("app.services.sms.dispatcher.generate_otp", return_value="123456"):
        # First request succeeds
        res1 = await client.post("/api/v1/auth/otp/send", json={"phone": phone})
        assert res1.status_code == 200

        # Second request within cooldown triggers HTTP 429
        res2 = await client.post("/api/v1/auth/otp/send", json={"phone": phone})
        assert res2.status_code == 429
        assert "Retry-After" in res2.headers
        assert res2.json()["detail"]["code"] == "COOLDOWN_ACTIVE"


@pytest.mark.asyncio
async def test_phone_rate_limiting(client: AsyncClient, test_redis: Redis):
    """
    Simulates exceeding the limit of 3 OTP requests in 10 minutes for a single phone.
    """
    phone = "+14155554444"

    with patch("app.services.sms.dispatcher.generate_otp", return_value="123456"):
        # Requests 1, 2, 3 succeed (clearing cooldown between sends for testing)
        for i in range(3):
            await test_redis.delete(f"cooldown:otp:{phone}")
            res = await client.post("/api/v1/auth/otp/send", json={"phone": phone})
            assert res.status_code == 200

        # 4th request exceeds rate limit
        await test_redis.delete(f"cooldown:otp:{phone}")
        res4 = await client.post("/api/v1/auth/otp/send", json={"phone": phone})
        assert res4.status_code == 429
        assert res4.json()["detail"]["code"] == "PHONE_RATE_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_brute_force_otp_wipe(client: AsyncClient, test_redis: Redis):
    """
    Simulates 5 wrong OTP submissions, verifying that the OTP is auto-deleted from Redis on the 6th.
    """
    phone = "+14155555555"

    with patch("app.services.sms.dispatcher.generate_otp", return_value="999999"):
        await client.post("/api/v1/auth/otp/send", json={"phone": phone})

        # Submit wrong OTP 5 times
        for _ in range(5):
            res = await client.post(
                "/api/v1/auth/otp/verify", json={"phone": phone, "otp": "000000"}
            )
            assert res.status_code == 400
            assert res.json()["detail"]["code"] == "INVALID_OTP"

        # 6th attempt triggers MAX_ATTEMPTS_EXCEEDED and wipes key
        res6 = await client.post(
            "/api/v1/auth/otp/verify", json={"phone": phone, "otp": "000000"}
        )
        assert res6.status_code == 400
        assert res6.json()["detail"]["code"] == "MAX_ATTEMPTS_EXCEEDED"

        # Verify key was wiped in Redis
        stored_hash = await test_redis.get(f"otp:{phone}")
        assert stored_hash is None


@pytest.mark.asyncio
async def test_registration_token_replay_blocked(client: AsyncClient):
    """
    Attack Simulation: An attacker tries to reuse a registration token that was already consumed.
    Must be rejected with HTTP 401.
    """
    phone = "+14155556666"

    with patch("app.services.sms.dispatcher.generate_otp", return_value="123456"):
        await client.post("/api/v1/auth/otp/send", json={"phone": phone})
        v_res = await client.post(
            "/api/v1/auth/otp/verify", json={"phone": phone, "otp": "123456"}
        )
        reg_token = v_res.json()["registration_token"]

        # First use succeeds
        res1 = await client.post(
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {reg_token}"},
            json={"name": "First Use"},
        )
        assert res1.status_code == 201

        # Replay attempt fails
        res2 = await client.post(
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {reg_token}"},
            json={"name": "Replay Attempt"},
        )
        assert res2.status_code == 401
        assert res2.json()["detail"]["code"] == "TOKEN_ALREADY_CONSUMED"


@pytest.mark.asyncio
async def test_scope_isolation(client: AsyncClient):
    """
    Security Test: A registration token cannot be used to access protected endpoints like /auth/me.
    """
    phone = "+14155557777"

    with patch("app.services.sms.dispatcher.generate_otp", return_value="123456"):
        await client.post("/api/v1/auth/otp/send", json={"phone": phone})
        v_res = await client.post(
            "/api/v1/auth/otp/verify", json={"phone": phone, "otp": "123456"}
        )
        reg_token = v_res.json()["registration_token"]

        # Attempt to call /me using the registration token
        me_res = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {reg_token}"},
        )
        assert me_res.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_theft_revocation(client: AsyncClient):
    """
    Security Test: Tests normal token rotation and simulates token theft where an old 
    rotated refresh token is replayed, causing full session family revocation.
    """
    phone = "+14155558888"

    # 1. Sign up user
    with patch("app.services.sms.dispatcher.generate_otp", return_value="123456"):
        await client.post("/api/v1/auth/otp/send", json={"phone": phone})
        v_res = await client.post(
            "/api/v1/auth/otp/verify", json={"phone": phone, "otp": "123456"}
        )
        reg_token = v_res.json()["registration_token"]
        signup_res = await client.post(
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {reg_token}"},
            json={"name": "Rotation User"},
        )
        token_1 = signup_res.json()["refresh_token"]

    # 2. Legitimate Rotation: Refresh token 1 -> issues token 2
    rotate_res = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": token_1}
    )
    assert rotate_res.status_code == 200
    token_2 = rotate_res.json()["refresh_token"]

    # 3. 🚨 Token Theft Simulation: Attacker tries to use already-rotated token 1
    theft_res = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": token_1}
    )
    assert theft_res.status_code == 401
    assert theft_res.json()["detail"]["code"] == "TOKEN_THEFT_DETECTED"

    # 4. As a result of theft detection, active token 2 must now also be revoked!
    victim_res = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": token_2}
    )
    assert victim_res.status_code == 401


@pytest.mark.asyncio
async def test_validation_errors(client: AsyncClient):
    """
    Verifies that malformed input formats are rejected with HTTP 422 by Pydantic.
    """
    # Malformed phone
    res1 = await client.post("/api/v1/auth/otp/send", json={"phone": "invalid-phone"})
    assert res1.status_code == 422

    # Malformed OTP (5 digits instead of 6)
    res2 = await client.post(
        "/api/v1/auth/otp/verify", json={"phone": "+14155552671", "otp": "12345"}
    )
    assert res2.status_code == 422
