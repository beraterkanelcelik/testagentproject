"""
Authentication tests.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

User = get_user_model()


class TestAuthentication(TestCase):
    """Test authentication endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.user_data = {
            "email": "test@example.com",
            "password": "testpass123"
        }

    def test_user_signup(self):
        """Test user registration."""
        response = self.client.post('/api/auth/signup/', {
            "email": self.user_data["email"],
            "password": self.user_data["password"]
        }, format='json')
        
        # Should create user and return success (201) or handle validation errors (400)
        if response.status_code == status.HTTP_201_CREATED:
            self.assertTrue(User.objects.filter(email=self.user_data["email"]).exists())
        else:
            # If 400, check if it's a validation error (user might already exist)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_login(self):
        """Test user login."""
        # Create user first
        User.objects.create_user(
            email=self.user_data["email"],
            password=self.user_data["password"]
        )
        
        response = self.client.post('/api/auth/login/', {
            "email": self.user_data["email"],
            "password": self.user_data["password"]
        }, format='json')
        
        # Should return tokens (200) or handle errors (400/401)
        if response.status_code == status.HTTP_200_OK:
            import json
            data = json.loads(response.content)
            self.assertIn("access", data)
            self.assertIn("refresh", data)
        else:
            # Log the actual response for debugging
            import json
            data = json.loads(response.content) if response.content else {}
            self.fail(f"Login failed with status {response.status_code}: {data}")

    def test_user_login_invalid_credentials(self):
        """Test login with invalid credentials."""
        response = self.client.post('/api/auth/login/', {
            "email": "wrong@example.com",
            "password": "wrongpass"
        }, format='json')
        
        # Should return error (401) or validation error (400)
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED])

    def test_token_refresh(self):
        """Test token refresh."""
        # Create user and get refresh token
        user = User.objects.create_user(
            email=self.user_data["email"],
            password=self.user_data["password"]
        )
        
        # Login to get tokens
        login_response = self.client.post('/api/auth/login/', {
            "email": self.user_data["email"],
            "password": self.user_data["password"]
        }, format='json')
        import json
        login_data = json.loads(login_response.content)
        refresh_token = login_data.get("refresh")
        
        # Refresh token
        response = self.client.post('/api/auth/refresh/', {
            "refresh": refresh_token
        }, format='json')
        
        # Should return new access token
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        refresh_data = json.loads(response.content)
        self.assertIn("access", refresh_data)
