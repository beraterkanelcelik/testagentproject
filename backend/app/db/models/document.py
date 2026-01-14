"""
Document models for file uploads and text storage.
"""
import hashlib
from django.db import models
from django.conf import settings


class Document(models.Model):
    """Represents an uploaded document file."""
    
    class Status(models.TextChoices):
        UPLOADED = 'UPLOADED', 'Uploaded'
        QUEUED = 'QUEUED', 'Queued'  # Waiting in Temporal queue
        EXTRACTED = 'EXTRACTED', 'Extracted'
        INDEXING = 'INDEXING', 'Indexing'
        READY = 'READY', 'Ready'
        FAILED = 'FAILED', 'Failed'
    
    class SourceType(models.TextChoices):
        UPLOAD = 'upload', 'Upload'
        URL = 'url', 'URL'
    
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='documents',
        db_index=True
    )
    title = models.CharField(max_length=255)
    source_type = models.CharField(
        max_length=20,
        choices=SourceType.choices,
        default=SourceType.UPLOAD
    )
    file = models.FileField(upload_to='documents/%Y/%m/%d/', null=True, blank=True)
    mime_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField()
    checksum = models.CharField(max_length=64, db_index=True)  # SHA-256 hex
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UPLOADED,
        db_index=True
    )
    error_message = models.TextField(blank=True, null=True)
    chunks_count = models.IntegerField(default=0)
    tokens_estimate = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'documents'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner', 'created_at'], name='documents_owner_i_6162db_idx'),
            models.Index(fields=['owner', 'status'], name='documents_owner_i_91a99b_idx'),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.owner.email})"
    
    def calculate_checksum(self, file_content):
        """Calculate SHA-256 checksum of file content."""
        return hashlib.sha256(file_content).hexdigest()


class DocumentText(models.Model):
    """Stores extracted text content from documents."""
    
    document = models.OneToOneField(
        Document,
        on_delete=models.CASCADE,
        related_name='extracted_text'
    )
    text = models.TextField()
    page_map = models.JSONField(default=dict, blank=True)  # {page_num: start_char, end_char}
    language = models.CharField(max_length=10, default='en', blank=True)
    extracted_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'document_texts'
    
    def __str__(self):
        return f"Text for {self.document.title}"
