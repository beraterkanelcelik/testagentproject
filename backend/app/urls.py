"""
URL configuration for app project.
"""
from django.contrib import admin
from django.urls import path
from app.api import health, chats, documents, agent
from app.account.api import auth, users

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),
    
    # Health check
    path('api/health/', health.health_check, name='health'),
    
    # Authentication
    path('api/auth/signup/', auth.signup, name='signup'),
    path('api/auth/login/', auth.login, name='login'),
    path('api/auth/refresh/', auth.refresh, name='refresh'),
    path('api/auth/logout/', auth.logout, name='logout'),
    path('api/auth/change-password/', auth.change_password, name='change_password'),
    
    # Users
    path('api/users/me/', users.get_current_user_endpoint, name='current_user'),
    path('api/users/me/update/', users.update_current_user, name='update_user'),
    path('api/users/me/stats/', users.get_user_stats, name='user_stats'),
    
    # Chats
    path('api/chats/', chats.chat_sessions, name='chat_sessions'),
    path('api/chats/delete-all/', chats.delete_all_chat_sessions, name='delete_all_chat_sessions'),
    path('api/chats/<int:session_id>/', chats.chat_session_detail, name='chat_session'),
    path('api/chats/<int:session_id>/messages/', chats.chat_messages, name='chat_messages'),
    path('api/chats/<int:session_id>/stats/', chats.chat_session_stats, name='chat_session_stats'),
    
    # Documents
    path('api/documents/', documents.documents, name='documents'),
    path('api/documents/<int:document_id>/', documents.document_detail, name='document_detail'),
    
    # Agent
    path('api/agent/run/', agent.run_agent, name='run_agent'),
    path('api/agent/stream/', agent.stream_agent, name='stream_agent'),
]
