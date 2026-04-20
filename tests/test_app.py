"""Tests para app.py — health endpoint y security headers."""


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get('/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'


class TestSecurityHeaders:
    def test_x_content_type_options(self, client):
        response = client.get('/health')
        assert response.headers.get('X-Content-Type-Options') == 'nosniff'

    def test_x_frame_options(self, client):
        response = client.get('/health')
        assert response.headers.get('X-Frame-Options') == 'DENY'

    def test_referrer_policy(self, client):
        response = client.get('/health')
        assert response.headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin'


class TestApiAuth:
    def test_api_softland_requires_auth(self, client):
        """Sin API_SECRET o Bearer token, las rutas API deben rechazar."""
        response = client.get('/api/softland/health')
        # Puede ser 401 o 404 dependiendo de la implementación
        assert response.status_code in (401, 403, 404)

    def test_api_tracking_requires_auth(self, client):
        response = client.get('/api/tracking/1001')
        assert response.status_code in (401, 403, 404)
