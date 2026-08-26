def test_theme_toggle_is_on_public_and_signed_in_pages(client):
    home = client.get("/")
    assert home.status_code == 200
    assert b'data-theme-toggle' in home.data
    assert b"js/theme.js" in home.data
    assert home.data.count(b'data-theme-toggle') == 1
    assert b'<meta name="google-adsense-account" content="ca-pub-3990201330574869">' in home.data

    login = client.get("/login")
    assert login.status_code == 200
    assert b'data-theme-toggle' in login.data
    assert b'name="google-adsense-account"' in login.data

    from tests.conftest import signup

    signup(client)
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert b'data-theme-toggle' in dashboard.data
    assert b"js/theme.js" in dashboard.data
    assert b'name="google-adsense-account"' in dashboard.data
