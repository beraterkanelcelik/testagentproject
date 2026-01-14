"""
URL configuration for app project.
"""
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from app.api import health, chats, documents, agent, rag, models
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
    path('api/documents/stream/', documents.stream_document_status, name='stream_document_status'),
    path('api/documents/<int:document_id>/', documents.document_detail, name='document_detail'),
    path('api/documents/<int:document_id>/file/', documents.document_file, name='document_file'),
    path('api/documents/<int:document_id>/chunks/', documents.document_chunks, name='document_chunks'),
    path('api/documents/<int:document_id>/index/', documents.document_index, name='document_index'),
    
    # Agent
    path('api/agent/stream/', agent.stream_agent, name='stream_agent'),
    path('api/agent/approve-tool/', agent.approve_tool, name='approve_tool'),
    
    # RAG
    path('api/rag/query/', rag.rag_query, name='rag_query'),
    
    # Models
    path('api/models/', models.get_available_models, name='available_models'),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
