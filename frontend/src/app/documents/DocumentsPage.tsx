import React, { useState, useEffect, useRef, useMemo } from 'react'
import { documentAPI, API_URL } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { getErrorMessage } from '@/lib/utils'

interface Document {
  id: number
  title: string
  status: 'UPLOADED' | 'QUEUED' | 'EXTRACTED' | 'INDEXING' | 'READY' | 'FAILED'
  chunks_count: number
  tokens_estimate: number
  size_bytes: number
  mime_type: string
  error_message?: string | null
  created_at: string
  updated_at: string
}

const StatusBadge = ({ status }: { status: Document['status'] }) => {
  const statusConfig = {
    UPLOADED: { label: 'Uploaded', className: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200' },
    QUEUED: { label: 'Queued', className: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200' },
    EXTRACTED: { label: 'Extracting...', className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' },
    INDEXING: { label: 'Indexing...', className: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200' },
    READY: { label: 'Ready', className: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' },
    FAILED: { label: 'Failed', className: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' },
  }

  const config = statusConfig[status] || statusConfig.UPLOADED

  return (
    <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${config.className}`}>
      {config.label}
    </span>
  )
}

const HighlightedText = ({ text, searchTerm }: { text: string; searchTerm: string }) => {
  if (!searchTerm.trim()) {
    return <p className="whitespace-pre-wrap">{text}</p>
  }

  const parts = []
  let lastIndex = 0
  const searchLower = searchTerm.toLowerCase()
  const textLower = text.toLowerCase()
  let index = textLower.indexOf(searchLower, lastIndex)

  while (index !== -1) {
    // Add text before the match
    if (index > lastIndex) {
      parts.push(
        <span key={`text-${lastIndex}`} className="whitespace-pre-wrap">
          {text.substring(lastIndex, index)}
        </span>
      )
    }
    
    // Add the highlighted match
    parts.push(
      <mark
        key={`match-${index}`}
        className="bg-yellow-200 dark:bg-yellow-900 text-yellow-900 dark:text-yellow-200 px-0.5 rounded"
      >
        {text.substring(index, index + searchTerm.length)}
      </mark>
    )
    
    lastIndex = index + searchTerm.length
    index = textLower.indexOf(searchLower, lastIndex)
  }
  
  // Add remaining text after the last match
  if (lastIndex < text.length) {
    parts.push(
      <span key={`text-${lastIndex}`} className="whitespace-pre-wrap">
        {text.substring(lastIndex)}
      </span>
    )
  }

  return <p className="whitespace-pre-wrap">{parts}</p>
}

interface Chunk {
  id: number
  chunk_index: number
  content: string
  start_offset: number | null
  end_offset: number | null
  metadata: Record<string, any>
  has_embedding: boolean
  embedding_model?: string
  created_at: string
}

interface DocumentDetail extends Document {
  extracted_text?: string | null
  page_map?: Record<number, { start_char: number; end_char: number }>
  language?: string | null
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [documentToDelete, setDocumentToDelete] = useState<number | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewDocument, setPreviewDocument] = useState<DocumentDetail | null>(null)
  const [previewChunks, setPreviewChunks] = useState<Chunk[]>([])
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [previewTab, setPreviewTab] = useState<'overview' | 'original' | 'text' | 'chunks'>('overview')
  const [chunkSearchTerm, setChunkSearchTerm] = useState('')
  const [expandedChunks, setExpandedChunks] = useState<Set<number>>(new Set())
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dropZoneRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadDocuments()
  }, [])

  // SSE connection for real-time document status updates
  // Always establish connection when page loads to receive updates
  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (!token) {
      return // No auth token, skip SSE connection
    }

    let abortController: AbortController | null = null
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null
    let reconnectTimeout: NodeJS.Timeout | null = null

    const connectSSE = async () => {
      try {
        abortController = new AbortController()
        const response = await fetch(`${API_URL}/api/documents/stream/`, {
          method: 'GET',
          headers: {
            'Authorization': `Bearer ${token}`,
          },
          signal: abortController.signal,
        })

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }

        if (!response.body) {
          throw new Error('Response body is null')
        }

        reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n\n')
          buffer = lines.pop() || ''

          for (const block of lines) {
            // SSE format is: "event: {type}\ndata: {json}\n\n"
            // Parse the block to extract the data line
            const dataLine = block.split('\n').find(line => line.startsWith('data: '))
            if (dataLine) {
              try {
                const data = JSON.parse(dataLine.slice(6))
                
                if (data.type === 'status_update') {
                  const update = data.data
                  const documentId = update.document_id
                  const newStatus = update.status

                  // Update document in state
                  setDocuments((prev) => {
                    const currentDoc = prev.find((d) => d.id === documentId)
                    
                    // Show toast when status changes to READY or FAILED
                    if (currentDoc) {
                      if (newStatus === 'READY' && currentDoc.status !== 'READY') {
                        toast.success(`Document "${currentDoc.title}" indexed successfully`)
                      } else if (newStatus === 'FAILED' && currentDoc.status !== 'FAILED') {
                        toast.error(
                          `Document "${currentDoc.title}" indexing failed: ${update.error_message || 'Unknown error'}`
                        )
                      }
                    }

                    // Update document with new status and optional fields
                    return prev.map((d) => {
                      if (d.id === documentId) {
                        return {
                          ...d,
                          status: newStatus,
                          chunks_count: update.chunks_count !== undefined ? update.chunks_count : d.chunks_count,
                          tokens_estimate: update.tokens_estimate !== undefined ? update.tokens_estimate : d.tokens_estimate,
                          error_message: update.error_message !== undefined ? update.error_message : d.error_message,
                        }
                      }
                      return d
                    })
                  })
                } else if (data.type === 'queue_complete') {
                  // Note: With per-document workflows, queue_complete is no longer published from individual workflows
                  // Keep connection open to receive updates from all document workflows
                  // Connection will close when component unmounts or user navigates away
                  console.debug('queue_complete event received (ignored - keeping connection open for all documents)')
                } else if (data.type === 'heartbeat') {
                  // Heartbeat received, connection is alive
                  // No action needed
                } else if (data.type === 'error') {
                  console.error('SSE error:', data.data)
                  if (data.data?.error && !data.data.retry) {
                    // Non-retryable error, close connection
                    return
                  }
                }
              } catch (error) {
                console.error('Error parsing SSE message:', error)
              }
            }
          }
        }
      } catch (error: any) {
        if (error.name === 'AbortError') {
          // Connection was aborted (component unmounted), this is expected
          return
        }
        console.error('SSE connection error:', error)
        // Retry connection after 3 seconds
        reconnectTimeout = setTimeout(() => {
          connectSSE()
        }, 3000)
      } finally {
        if (reader) {
          try {
            await reader.cancel()
          } catch (e) {
            // Ignore cancel errors
          }
        }
      }
    }

    connectSSE()

    // Cleanup on unmount
    return () => {
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout)
      }
      if (abortController) {
        abortController.abort()
      }
      if (reader) {
        reader.cancel().catch(() => {
          // Ignore cancel errors
        })
      }
    }
  }, []) // Only run once on mount - keep connection open to receive all updates

  const loadDocuments = async () => {
    setLoading(true)
    try {
      const response = await documentAPI.getDocuments()
      // Backend returns { results: [...], count, page, ... }
      setDocuments(response.data.results || [])
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to load documents'))
    } finally {
      setLoading(false)
    }
  }

  const handleFileSelect = async (files: FileList | null) => {
    if (!files || files.length === 0) return

    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        const tempId = Date.now() + Math.random() // Unique temporary ID
        try {
          // Optimistically add document to list
          const optimisticDoc: Document = {
            id: tempId, // Temporary ID
            title: file.name,
            status: 'UPLOADED',
            chunks_count: 0,
            tokens_estimate: 0,
            size_bytes: file.size,
            mime_type: file.type,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }
          setDocuments((prev) => [optimisticDoc, ...prev])

          // Upload document
          const response = await documentAPI.uploadDocument(file)
          const uploadedDoc = response.data

          // Replace optimistic doc with real one
          setDocuments((prev) =>
            prev.map((doc) =>
              doc.id === tempId ? uploadedDoc : doc
            )
          )

          // Show success message based on status
          if (uploadedDoc.status === 'READY') {
            toast.success(`File "${file.name}" uploaded and indexed successfully`)
          } else if (uploadedDoc.status === 'FAILED') {
            toast.error(
              `File "${file.name}" upload failed: ${uploadedDoc.error_message || 'Unknown error'}`
            )
          } else {
            toast.success(`File "${file.name}" uploaded successfully (indexing in progress)`)
            // Status will be updated automatically by the polling effect
          }
        } catch (error: unknown) {
          // Remove optimistic doc on error
          setDocuments((prev) =>
            prev.filter((doc) => doc.id !== tempId)
          )
          toast.error(
            getErrorMessage(error, `Failed to upload "${file.name}"`)
          )
        }
      }
      // Refresh list to get latest status
      await loadDocuments()
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to upload document'))
    } finally {
      setUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  // Removed pollDocumentStatus - now handled by useEffect polling for all processing documents

  const handleDelete = (id: number, e: React.MouseEvent) => {
    e.stopPropagation()
    setDocumentToDelete(id)
    setDeleteDialogOpen(true)
  }

  const confirmDelete = async () => {
    if (documentToDelete === null) return

    try {
      await documentAPI.deleteDocument(documentToDelete)
      toast.success('Document deleted successfully')
      await loadDocuments()
      setDeleteDialogOpen(false)
      setDocumentToDelete(null)
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to delete document'))
    }
  }

  const cancelDelete = () => {
    setDeleteDialogOpen(false)
    setDocumentToDelete(null)
  }

  const handlePreview = async (doc: Document) => {
    setPreviewOpen(true)
    setLoadingPreview(true)
    setPreviewTab('overview')
    
    try {
      // Load document details and chunks in parallel
      const [detailResponse, chunksResponse] = await Promise.all([
        documentAPI.getDocument(doc.id),
        documentAPI.getDocumentChunks(doc.id).catch((err) => {
          console.error('Error loading chunks:', err)
          return { data: { chunks: [], total_chunks: 0 } }
        })
      ])
      
      setPreviewDocument(detailResponse.data)
      // Handle chunks response - backend returns { chunks: [...], total_chunks: N }
      const chunks = chunksResponse.data?.chunks || []
      setPreviewChunks(Array.isArray(chunks) ? chunks : [])
      // Reset search and expanded chunks when loading new document
      setChunkSearchTerm('')
      setExpandedChunks(new Set())
      
      // Debug: Log if chunks are missing
      if (chunks.length === 0 && detailResponse.data?.chunks_count > 0) {
        console.warn('Chunks mismatch:', {
          chunksCount: detailResponse.data.chunks_count,
          chunksReturned: chunks.length,
          chunksResponse: chunksResponse.data
        })
      }
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to load document preview'))
      setPreviewOpen(false)
    } finally {
      setLoadingPreview(false)
    }
  }

  const closePreview = () => {
    setPreviewOpen(false)
    setPreviewDocument(null)
    setPreviewChunks([])
    setChunkSearchTerm('')
    setExpandedChunks(new Set())
  }

  // Drag and drop handlers
  const handleDrag = (e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true)
    } else if (e.type === 'dragleave') {
      setDragActive(false)
    }
  }

  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelect(e.dataTransfer.files)
    }
  }

  // Sort documents by updated_at (most recent first)
  const sortedDocuments = [...documents].sort((a, b) => {
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  })

  return (
    <>
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-3xl font-bold">Documents</h1>
          <Button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="rounded-lg"
          >
            {uploading ? 'Uploading...' : 'Upload Document'}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={(e) => handleFileSelect(e.target.files)}
            className="hidden"
            disabled={uploading}
          />
        </div>

        {/* Upload Area */}
        <div
          ref={dropZoneRef}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-12 text-center mb-8 transition-colors ${
            dragActive
              ? 'border-primary bg-primary/5'
              : 'border-muted hover:border-primary/50 hover:bg-muted/50'
          }`}
        >
          <svg
            className="w-12 h-12 mx-auto mb-4 text-muted-foreground"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
            />
          </svg>
          <p className="text-muted-foreground mb-2">
            Drag and drop files here, or click to select
          </p>
          <p className="text-xs text-muted-foreground">
            Supported formats: PDF, TXT, DOC, DOCX
          </p>
        </div>

        {/* Documents List */}
        {loading ? (
          <div className="text-center py-12">
            <div className="inline-flex items-center gap-2 text-muted-foreground">
              <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span>Loading documents...</span>
            </div>
          </div>
        ) : sortedDocuments.length === 0 ? (
          <div className="border rounded-lg p-12 text-center">
            <svg
              className="w-16 h-16 mx-auto mb-4 text-muted-foreground"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            <p className="text-muted-foreground mb-4">No documents yet</p>
            <Button
              onClick={() => fileInputRef.current?.click()}
              className="rounded-lg"
            >
              Upload Your First Document
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            {sortedDocuments.map((doc: Document) => (
              <div
                key={doc.id}
                className="p-4 border rounded-lg hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3 flex-1">
                    <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                      <svg
                        className="w-5 h-5 text-primary"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                        />
                      </svg>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 
                          className="font-medium text-sm truncate cursor-pointer hover:text-primary"
                          onClick={() => handlePreview(doc)}
                        >
                          {doc.title}
                        </h3>
                        <StatusBadge status={doc.status} />
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">
                        Uploaded {new Date(doc.created_at).toLocaleDateString()} • 
                        Updated {new Date(doc.updated_at).toLocaleDateString()}
                        {doc.chunks_count > 0 && ` • ${doc.chunks_count} chunks`}
                        {doc.status === 'FAILED' && doc.error_message && (
                          <span className="block text-destructive mt-1">
                            Error: {doc.error_message}
                          </span>
                        )}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handlePreview(doc)}
                      className="p-2 text-muted-foreground hover:text-primary transition-colors rounded-lg hover:bg-primary/10"
                      aria-label="Preview document"
                      title="Preview document"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                      </svg>
                    </button>
                    <button
                      onClick={(e) => handleDelete(doc.id, e)}
                      className="p-2 text-muted-foreground hover:text-destructive transition-colors rounded-lg hover:bg-destructive/10"
                      aria-label="Delete document"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                        />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Delete Confirmation Dialog */}
      {deleteDialogOpen && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          onClick={cancelDelete}
        >
          <div
            className="bg-background border rounded-lg p-6 max-w-md w-full mx-4 shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold mb-2">Delete Document</h3>
            <p className="text-muted-foreground mb-6">
              Are you sure you want to delete this document? This action cannot be undone.
            </p>
            <div className="flex justify-end gap-3">
              <Button variant="outline" onClick={cancelDelete} className="rounded-lg">
                Cancel
              </Button>
              <Button variant="destructive" onClick={confirmDelete} className="rounded-lg">
                Delete
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Document Preview Modal */}
      {previewOpen && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={closePreview}
        >
          <div
            className="bg-background border rounded-lg max-w-6xl w-full max-h-[90vh] flex flex-col shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b">
              <h2 className="text-xl font-semibold">
                {previewDocument?.title || 'Document Preview'}
              </h2>
              <button
                onClick={closePreview}
                className="p-2 text-muted-foreground hover:text-foreground transition-colors rounded-lg hover:bg-muted"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Tabs */}
            <div className="flex border-b">
              <button
                onClick={() => setPreviewTab('overview')}
                className={`px-6 py-3 text-sm font-medium transition-colors ${
                  previewTab === 'overview'
                    ? 'border-b-2 border-primary text-primary'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                Overview
              </button>
              <button
                onClick={() => setPreviewTab('original')}
                className={`px-6 py-3 text-sm font-medium transition-colors ${
                  previewTab === 'original'
                    ? 'border-b-2 border-primary text-primary'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                Original Document
              </button>
              <button
                onClick={() => setPreviewTab('text')}
                className={`px-6 py-3 text-sm font-medium transition-colors ${
                  previewTab === 'text'
                    ? 'border-b-2 border-primary text-primary'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                Extracted Text
              </button>
              <button
                onClick={() => setPreviewTab('chunks')}
                className={`px-6 py-3 text-sm font-medium transition-colors ${
                  previewTab === 'chunks'
                    ? 'border-b-2 border-primary text-primary'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                Chunks ({previewChunks.length})
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-auto p-6">
              {loadingPreview ? (
                <div className="flex items-center justify-center py-12">
                  <div className="inline-flex items-center gap-2 text-muted-foreground">
                    <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <span>Loading preview...</span>
                  </div>
                </div>
              ) : previewTab === 'overview' ? (
                <div className="space-y-6">
                  {previewDocument && (
                    <>
                      <div>
                        <h3 className="text-sm font-semibold mb-3">Document Information</h3>
                        <div className="grid grid-cols-2 gap-4 text-sm">
                          <div>
                            <span className="text-muted-foreground">Status:</span>
                            <div className="mt-1">
                              <StatusBadge status={previewDocument.status} />
                            </div>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Type:</span>
                            <p className="mt-1">{previewDocument.mime_type}</p>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Size:</span>
                            <p className="mt-1">{(previewDocument.size_bytes / 1024).toFixed(2)} KB</p>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Chunks:</span>
                            <p className="mt-1">{previewDocument.chunks_count}</p>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Tokens (est.):</span>
                            <p className="mt-1">{previewDocument.tokens_estimate.toLocaleString()}</p>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Language:</span>
                            <p className="mt-1">{previewDocument.language || 'Unknown'}</p>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Created:</span>
                            <p className="mt-1">{new Date(previewDocument.created_at).toLocaleString()}</p>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Updated:</span>
                            <p className="mt-1">{new Date(previewDocument.updated_at).toLocaleString()}</p>
                          </div>
                        </div>
                      </div>
                      {previewDocument.error_message && (
                        <div className="p-4 bg-destructive/10 border border-destructive/20 rounded-lg">
                          <p className="text-sm font-semibold text-destructive mb-1">Error Message</p>
                          <p className="text-sm text-destructive/80">{previewDocument.error_message}</p>
                        </div>
                      )}
                    </>
                  )}
                </div>
              ) : previewTab === 'original' ? (
                <div>
                  {previewDocument ? (
                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-semibold">Original Document</h3>
                        <a
                          href={`${API_URL}/api/documents/${previewDocument.id}/file/?token=${encodeURIComponent(localStorage.getItem('access_token') || '')}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-primary hover:underline"
                        >
                          Open in new tab
                        </a>
                      </div>
                      <div className="border rounded-lg overflow-hidden bg-muted/50">
                        {previewDocument.mime_type === 'application/pdf' ? (
                          <div className="relative w-full h-[70vh]">
                            <iframe
                              key={`pdf-${previewDocument.id}`}
                              src={`${API_URL}/api/documents/${previewDocument.id}/file/?token=${encodeURIComponent(localStorage.getItem('access_token') || '')}`}
                              className="w-full h-full border-0"
                              title={previewDocument.title}
                              onLoad={() => {
                                console.log('PDF iframe loaded successfully')
                              }}
                              onError={(e) => {
                                console.error('Iframe load error:', e)
                              }}
                            />
                            <div className="absolute top-2 right-2 text-xs text-muted-foreground bg-background/80 px-2 py-1 rounded">
                              {previewDocument.mime_type}
                            </div>
                            <div className="absolute bottom-2 left-2 text-xs text-muted-foreground">
                              <a
                                href={`${API_URL}/api/documents/${previewDocument.id}/file/?token=${encodeURIComponent(localStorage.getItem('access_token') || '')}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-primary hover:underline"
                              >
                                Can't see the PDF? Open in new tab
                              </a>
                            </div>
                          </div>
                        ) : (
                          <div className="p-8 text-center text-muted-foreground">
                            <p>Preview not available for this file type</p>
                            <a
                              href={`${API_URL}/api/documents/${previewDocument.id}/file/?token=${encodeURIComponent(localStorage.getItem('access_token') || '')}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-primary hover:underline mt-2 inline-block"
                            >
                              Download file
                            </a>
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="text-center py-12 text-muted-foreground">
                      <p>Document not available</p>
                    </div>
                  )}
                </div>
              ) : previewTab === 'text' ? (
                <div>
                  {previewDocument?.extracted_text ? (
                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-semibold">Extracted Text</h3>
                        <span className="text-xs text-muted-foreground">
                          {previewDocument.extracted_text.length.toLocaleString()} characters
                        </span>
                      </div>
                      <div className="bg-muted/50 rounded-lg p-4 max-h-[60vh] overflow-auto">
                        <pre className="whitespace-pre-wrap text-sm font-mono">
                          {previewDocument.extracted_text}
                        </pre>
                      </div>
                    </div>
                  ) : (
                    <div className="text-center py-12 text-muted-foreground">
                      <p>No extracted text available</p>
                      <p className="text-xs mt-2">Text extraction may not have completed yet</p>
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold">Document Chunks</h3>
                    <span className="text-xs text-muted-foreground">
                      {previewChunks.length} chunks
                    </span>
                  </div>
                  
                  {/* Search input */}
                  {previewChunks.length > 0 && (
                    <div className="relative">
                      <input
                        type="text"
                        placeholder="Search chunks..."
                        value={chunkSearchTerm}
                        onChange={(e) => setChunkSearchTerm(e.target.value)}
                        className="w-full px-3 py-2 pl-10 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary"
                      />
                      <svg
                        className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                        />
                      </svg>
                      {chunkSearchTerm && (
                        <button
                          onClick={() => setChunkSearchTerm('')}
                          className="absolute right-3 top-2.5 text-muted-foreground hover:text-foreground"
                        >
                          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      )}
                    </div>
                  )}
                  
                  {previewChunks.length === 0 ? (
                    <div className="text-center py-12 text-muted-foreground">
                      <p>No chunks available</p>
                      <p className="text-xs mt-2">Document may not be indexed yet</p>
                    </div>
                  ) : (() => {
                    // Filter chunks based on search term
                    const filteredChunks = previewChunks.filter((chunk) => {
                      if (!chunkSearchTerm.trim()) return true
                      const searchLower = chunkSearchTerm.toLowerCase()
                      return chunk.content.toLowerCase().includes(searchLower)
                    })
                    
                    return (
                      <div className="space-y-3">
                        {filteredChunks.length === 0 ? (
                          <div className="text-center py-8 text-muted-foreground">
                            <p>No chunks match your search</p>
                          </div>
                        ) : (
                          filteredChunks.map((chunk) => {
                            const isExpanded = expandedChunks.has(chunk.id)
                            const hasMatch = chunkSearchTerm 
                              ? chunk.content.toLowerCase().includes(chunkSearchTerm.toLowerCase())
                              : false
                            
                            return (
                              <div
                                key={chunk.id}
                                className="border rounded-lg hover:bg-muted/50 transition-colors"
                              >
                                <div className="p-4">
                                  <div className="flex items-start justify-between mb-2">
                                    <div className="flex items-center gap-2 flex-1">
                                      <button
                                        onClick={() => {
                                          setExpandedChunks((prev) => {
                                            const next = new Set(prev)
                                            if (next.has(chunk.id)) {
                                              next.delete(chunk.id)
                                            } else {
                                              next.add(chunk.id)
                                            }
                                            return next
                                          })
                                        }}
                                        className="flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
                                      >
                                        <svg
                                          className={`h-3 w-3 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                                          fill="none"
                                          stroke="currentColor"
                                          viewBox="0 0 24 24"
                                        >
                                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                        </svg>
                                        Chunk #{chunk.chunk_index}
                                      </button>
                                      {chunk.metadata?.page && (
                                        <span className="text-xs text-muted-foreground">
                                          Page {chunk.metadata.page}
                                        </span>
                                      )}
                                      {chunk.has_embedding && (
                                        <span className="text-xs px-2 py-0.5 bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200 rounded-full">
                                          Embedded
                                        </span>
                                      )}
                                      {hasMatch && (
                                        <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 rounded-full">
                                          Match
                                        </span>
                                      )}
                                    </div>
                                    <div className="text-xs text-muted-foreground">
                                      {chunk.content.length} chars
                                    </div>
                                  </div>
                                  
                                  {isExpanded && (
                                    <div className="mt-3 space-y-2">
                                      <div className="bg-muted/50 rounded p-3 text-sm">
                                        {chunkSearchTerm.trim() ? (
                                          <HighlightedText text={chunk.content} searchTerm={chunkSearchTerm} />
                                        ) : (
                                          <p className="whitespace-pre-wrap">{chunk.content}</p>
                                        )}
                                      </div>
                                      {chunk.start_offset !== null && chunk.end_offset !== null && (
                                        <p className="text-xs text-muted-foreground">
                                          Position: {chunk.start_offset} - {chunk.end_offset}
                                        </p>
                                      )}
                                    </div>
                                  )}
                                </div>
                              </div>
                            )
                          })
                        )}
                      </div>
                    )
                  })()}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
