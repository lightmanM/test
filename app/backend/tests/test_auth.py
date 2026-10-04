def test_login_creates_user_and_sets_session(client, login):
    resp = login("Alice")
    assert resp.status_code == 200
    assert resp.json() == {"username": "alice"}
    assert client.get("/api/me").json() == {"username": "alice"}


def test_me_requires_session(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/workflows").status_code == 401


def test_wrong_passcode_rejected(client, login):
    assert login(passcode="nope").status_code == 401


def test_invalid_usernames_rejected(client, login):
    for name in ["ab", "a" * 21, "bad name", "-dash", "dash-", "émile"]:
        assert login(name).status_code == 422, name


def test_user_cap(client, login, services):
    services.settings.max_users = 2
    assert login("user1").status_code == 200
    assert login("user2").status_code == 200
    resp = login("user3")
    assert resp.status_code == 403
    assert "full" in resp.json()["detail"]
    assert login("user1").status_code == 200  # existing users can still sign in


def test_logout_clears_session(client, login):
    login()
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401


def test_forged_cookie_rejected(client):
    client.cookies.set("wd_session", "not-a-real-token")
    assert client.get("/api/me").status_code == 401


def test_admin_login_and_overview(client, login):
    login("bob")
    assert client.get("/api/admin/overview").status_code == 401
    assert client.post("/api/admin/login", json={"passcode": "wrong"}).status_code == 401
    assert client.post("/api/admin/login", json={"passcode": "adminpass"}).status_code == 204
    overview = client.get("/api/admin/overview").json()
    assert [u["username"] for u in overview["users"]] == ["bob"]
    assert overview["fake_platforms"] is True


def test_user_session_is_not_admin(client, login):
    login()
    client.cookies.set("wd_admin", client.cookies.get("wd_session"))
    assert client.get("/api/admin/overview").status_code == 401


def test_cookie_for_another_username_is_rejected(client, login, services):
    login("alice")
    forged = services.signer.dumps({"uid": 1, "username": "mallory"}, "wd_session")
    client.cookies.set("wd_session", forged)
    assert client.get("/api/me").status_code == 401
