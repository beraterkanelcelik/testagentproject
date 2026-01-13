"""
Chat message model.
"""
from django.db import models
from .session import ChatSession


class Message(models.Model):
    """Message model for storing chat messages."""
    
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]
    
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    tokens_used = models.IntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'messages'
        ordering = ['created_at']
        verbose_name = 'Message'
        verbose_name_plural = 'Messages'
        indexes = [
            models.Index(fields=['session', 'role', '-created_at']),
            # Note: JSON field indexes (e.g., metadata__run_id) require PostgreSQL
            # and may need to be created via raw SQL migration for optimal performance
        ]
    
    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."
