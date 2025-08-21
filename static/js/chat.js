class BankingChatClient {
  constructor(sessionId, hasAnyDocument, initialDocs, selectedDocumentId) {
    this.sessionId = sessionId;
    this.socket = io();
    this.hasAnyDocument = hasAnyDocument;
    this.isConnected = false;

    // Elements
    this.chatMessages = document.getElementById('chatMessages');
    this.messageInput = document.getElementById('messageInput');
    this.sendBtn = document.getElementById('sendMessageBtn');
    this.clearBtn = document.getElementById('clearChatBtn');
    this.exportBtn = document.getElementById('exportChatBtn');
    this.typingIndicator = document.getElementById('typingIndicator');
    this.chatStatus = document.getElementById('chatStatus');
    this.uploadBtn = document.getElementById('uploadBtn');
    this.uploadInput = document.getElementById('uploadInput');
    this.dropOverlay = document.getElementById('dropOverlay');
    this.tokenUsage = document.getElementById('tokenUsage');

    // Documents dropdown
    this.docDropdownBtn = document.getElementById('docDropdownBtn');
    this.documentsMenu = document.getElementById('documentsMenu');
    this.documents = initialDocs || [];
    this.selectedDocumentId = selectedDocumentId || (this.documents[0]?.id || null);

    this.renderDocumentsMenu();

    this.registerSocketEvents();
    this.registerUIEvents();
    this.updateChatState();
  }

  registerSocketEvents() {
    this.socket.on('connect', () => { this.isConnected = true; this.updateChatState(); });
    this.socket.on('disconnect', () => { this.isConnected = false; this.updateChatState(); });
    this.socket.on('connected', () => {});
    this.socket.on('typing', () => this.showTyping());
    this.socket.on('message_response', (data) => {
      this.hideTyping();
      if (data.success) {
        this.addMessage('assistant', data.message, data.timestamp, data.content_type || 'text');
        if (this.tokenUsage && data.tokens_used !== undefined) {
          this.tokenUsage.textContent = `Tokens: ${data.tokens_used}`;
        }
      } else {
        this.addErrorMessage(data.error || 'Failed to get response');
      }
    });
    this.socket.on('document_processed', (data) => {
      // Add to documents list and select it
      this.documents.push({ id: data.id, filename: data.filename });
      this.selectedDocumentId = data.id;
      this.hasAnyDocument = true;
      this.renderDocumentsMenu();
      this.updateChatState();
      const summaryPart = data.summary ? `<br><small class="text-muted">Summary: ${this.escapeHtml(data.summary)}</small>` : '';
      this.addSystemMessage(`Document "${this.escapeHtml(data.filename)}" processed.${summaryPart}`);
    });
  }

  registerUIEvents() {
    if (this.sendBtn) this.sendBtn.addEventListener('click', () => this.sendMessage());
    if (this.messageInput) {
      this.messageInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          this.sendMessage();
        }
      });
    }
    if (this.clearBtn) this.clearBtn.addEventListener('click', () => this.clearChat());
    if (this.exportBtn) this.exportBtn.addEventListener('click', () => this.exportChat());

    // Upload button
    if (this.uploadBtn && this.uploadInput) {
      this.uploadBtn.addEventListener('click', () => this.uploadInput.click());
      this.uploadInput.addEventListener('change', async (e) => {
        const file = e.target.files && e.target.files[0];
        if (file) await this.uploadDocument(file);
      });
    }

    // Drag and drop on the chat card body
    const cardBody = this.chatMessages?.closest('.card-body');
    if (cardBody) {
      ['dragenter','dragover'].forEach(evt => cardBody.addEventListener(evt, (e) => this.onDragOver(e)));
      ['dragleave','drop'].forEach(evt => cardBody.addEventListener(evt, (e) => this.onDragLeaveOrDrop(e)));
      cardBody.addEventListener('drop', async (e) => this.onDrop(e));
    }
  }

  onDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    this.dropOverlay?.classList.remove('d-none');
  }
  onDragLeaveOrDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    this.dropOverlay?.classList.add('d-none');
  }
  async onDrop(e) {
    const files = e.dataTransfer?.files;
    if (files && files.length > 0) {
      const file = files[0];
      await this.uploadDocument(file);
    }
  }

  updateChatState() {
    // Allow chatting even without any document; document enhances context but isn't required.
    const canChat = this.isConnected;
    if (this.messageInput) this.messageInput.disabled = !canChat;
    if (this.sendBtn) this.sendBtn.disabled = !canChat;
    if (this.chatStatus) {
      if (!this.isConnected) {
        this.chatStatus.textContent = 'Connecting…';
      } else if (this.hasAnyDocument) {
        this.chatStatus.textContent = 'Ready (document context available)';
      } else {
        this.chatStatus.textContent = 'Ready (no document uploaded yet)';
      }
    }
    if (this.messageInput) {
      this.messageInput.placeholder = this.hasAnyDocument
        ? 'Ask about your document or your accounts…'
        : 'Ask about your accounts or upload a bill…';
    }
  }

  async sendMessage() {
    const msg = this.messageInput.value.trim();
    if (!msg || !this.isConnected) return;
    this.addMessage('user', msg);
    this.messageInput.value = '';
    this.showTyping();
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ message: msg })
      });
      const data = await res.json();
      this.hideTyping();
      if (res.ok && data.success) {
        this.addMessage('assistant', data.response, data.timestamp, data.content_type || 'text');
        if (this.tokenUsage && data.meta && data.meta.tokens_used !== undefined) {
          this.tokenUsage.textContent = `Tokens: ${data.meta.tokens_used}`;
        }
      } else {
        this.addErrorMessage(data.error || 'Failed to get response');
      }
    } catch (e) {
      this.hideTyping();
      this.addErrorMessage('Network error: could not send message');
    }
  }

  async uploadDocument(file) {
    // Render a local thumbnail preview immediately
    await this.addDocumentPreview(file);

    // Validate extension
    const name = (file?.name || '').toLowerCase();
    if (!name.match(/\.(pdf|png|jpg|jpeg)$/)) {
      this.addErrorMessage('Invalid file type. Please upload PDF, PNG, JPG, or JPEG.');
      return;
    }

    // Announce analysis start
    this.addSystemMessage(`<i class="fas fa-spinner fa-spin me-2"></i>Analyzing "${this.escapeHtml(file.name)}"…`);

    try {
      const form = new FormData();
      form.append('document', file);
      const res = await fetch('/api/analyze', { method: 'POST', body: form });
      const data = await res.json();
      if (res.ok && data.success) {
        this.hasAnyDocument = true;
        this.selectedDocumentId = data.id;
        this.renderDocumentsMenu();
        this.updateChatState();
        const summaryPart = data.summary ? `<br><small class="text-muted">Summary: ${this.escapeHtml(data.summary)}</small>` : '';
        this.addSystemMessage(`Document "${this.escapeHtml(data.filename)}" processed.${summaryPart}`);
      } else {
        this.addErrorMessage(data.error || 'Failed to analyze document');
      }
    } catch (e) {
      this.addErrorMessage('Network error: could not upload document');
    }
  }

  async addDocumentPreview(file) {
    // If it's an image, show directly
    if (file && file.type && file.type.startsWith('image/')) {
      const url = URL.createObjectURL(file);
      const html = `
        <div class="doc-preview">
          <img class="doc-thumb" src="${url}" alt="${this.escapeHtml(file.name)} thumbnail">
          <div class="small text-muted mt-1"><i class="fas fa-image me-1"></i>${this.escapeHtml(file.name)}</div>
        </div>
      `;
      this.addMessage('user', html, null, 'html');
      // Optional: revoke later (leave as-is to avoid race conditions)
      return;
    }

    // If it's a PDF, render first page via PDF.js (if available)
    const isPdf = (file && ((file.type === 'application/pdf') || /\.pdf$/i.test(file.name)));
    if (isPdf && window.pdfjsLib) {
      try {
        const buffer = await file.arrayBuffer();
        const pdf = await pdfjsLib.getDocument({ data: buffer }).promise;
        const page = await pdf.getPage(1);
        const viewport = page.getViewport({ scale: 1 });
        const targetW = 180;
        const scale = targetW / viewport.width;
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        const scaledViewport = page.getViewport({ scale });
        canvas.width = Math.ceil(scaledViewport.width);
        canvas.height = Math.ceil(scaledViewport.height);
        await page.render({ canvasContext: ctx, viewport: scaledViewport }).promise;
        const dataUrl = canvas.toDataURL('image/png');
        const html = `
          <div class="doc-preview">
            <div class="pdf-badge">PDF</div>
            <img class="doc-thumb" src="${dataUrl}" alt="${this.escapeHtml(file.name)} page 1">
            <div class="small text-muted mt-1"><i class="fas fa-file-pdf me-1"></i>${this.escapeHtml(file.name)}</div>
          </div>
        `;
        this.addMessage('user', html, null, 'html');
        return;
      } catch (err) {
        // fall through to fallback
      }
    }

    // Fallback for unknown or unrenderable files
    const icon = isPdf ? 'fa-file-pdf' : 'fa-file';
    const html = `
      <div class="doc-preview">
        <div class="doc-fallback"><i class="fas ${icon} fa-2x"></i></div>
        <div class="small text-muted mt-1">${this.escapeHtml(file?.name || 'document')}</div>
      </div>
    `;
    this.addMessage('user', html, null, 'html');
  }

  renderDocumentsMenu() {
    const menu = this.documentsMenu;
    if (!menu) return;
    menu.innerHTML = '';
    if (this.documents.length === 0) {
      menu.innerHTML = '<li><span class="dropdown-item-text text-muted">No documents</span></li>';
      return;
    }
    this.documents.forEach(doc => {
      const li = document.createElement('li');
      li.innerHTML = `
        <div class="dropdown-item d-flex justify-content-between align-items-center">
          <div>
            <input type="radio" name="docSelect" ${doc.id === this.selectedDocumentId ? 'checked' : ''} />
            <span class="ms-2">${this.escapeHtml(doc.filename)}</span>
          </div>
          <button class="btn btn-sm btn-outline-danger"><i class="fas fa-trash"></i></button>
        </div>
      `;
      const radio = li.querySelector('input[type="radio"]');
      radio.addEventListener('change', async () => {
        await this.selectDocument(doc.id);
      });
      const delBtn = li.querySelector('button');
      delBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await this.deleteDocument(doc.id);
      });
      menu.appendChild(li);
    });
  }

  async refreshDocuments() {
    const res = await fetch('/api/documents');
    const data = await res.json();
    if (res.ok && data.success) {
      this.documents = data.documents || [];
      this.selectedDocumentId = data.selected_document_id || (this.documents[0]?.id || null);
      this.renderDocumentsMenu();
      this.hasAnyDocument = this.documents.length > 0;
      this.updateChatState();
    }
  }

  async selectDocument(id) {
    const res = await fetch('/api/documents/select', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ id })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      this.selectedDocumentId = id;
      await this.refreshDocuments();
      this.addSystemMessage(`Selected document changed.`);
    } else {
      this.addErrorMessage(data.error || 'Failed to select document');
    }
  }

  async deleteDocument(id) {
    const res = await fetch(`/api/documents/${encodeURIComponent(id)}`, { method: 'DELETE' });
    const data = await res.json();
    if (res.ok && data.success) {
      await this.refreshDocuments();
      this.addSystemMessage(`Document removed.`);
    } else {
      this.addErrorMessage(data.error || 'Failed to delete document');
    }
  }

  addMessage(role, content, timestamp = null, contentType = 'text') {
    const wrap = document.createElement('div');
    wrap.className = `message mb-2 ${role === 'user' ? 'text-end' : ''}`;
    const isUser = role === 'user';
    const icon = isUser ? 'fa-user' : 'fa-robot';
    const bg = isUser ? 'bg-primary text-white' : 'bg-light';
    const timeStr = timestamp ? new Date(timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();

    const contentHtml = contentType === 'html' ? content : this.format(content);

    wrap.innerHTML = `
      <div class="d-inline-block ${bg} rounded px-3 py-2 max-width-80">
        <div class="d-flex align-items-start">
          <i class="fas ${icon} me-2 mt-1"></i>
          <div>
            <div class="message-content">${contentHtml}</div>
            <small class="opacity-75 d-block mt-1">${timeStr}</small>
          </div>
        </div>
      </div>
    `;
    this.chatMessages.appendChild(wrap);
    this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
  }

  addSystemMessage(content) {
    const wrap = document.createElement('div');
    wrap.className = 'text-center';
    wrap.innerHTML = `<div class="alert alert-info d-inline-block">${content}</div>`;
    this.chatMessages.appendChild(wrap);
    this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
  }

  addErrorMessage(err) {
    const wrap = document.createElement('div');
    wrap.innerHTML = `<div class="alert alert-danger"><i class="fas fa-exclamation-triangle me-2"></i>${this.escapeHtml(err)}</div>`;
    this.chatMessages.appendChild(wrap);
    this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
  }

  showTyping() { this.typingIndicator.classList.remove('d-none'); }
  hideTyping() { this.typingIndicator.classList.add('d-none'); }

  format(txt) {
    return this.escapeHtml(txt)
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/```([\s\S]*?)```/g, '<pre class="bg-dark text-light p-2 rounded"><code>$1</code></pre>')
      .replace(/`(.*?)`/g, '<code class="bg-light px-1 rounded">$1</code>')
      .replace(/\n/g, '<br>');
  }

  escapeHtml(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async clearChat() {
    if (!confirm('Clear chat history?')) return;
    try {
      const res = await fetch('/api/clear_chat', { method: 'POST' });
      if (res.ok) {
        this.chatMessages.innerHTML = '';
        this.tokenUsage && (this.tokenUsage.textContent = '');
      }
    } catch (e) {
      this.addErrorMessage('Failed to clear chat');
    }
  }

  async exportChat() {
    try {
      const res = await fetch('/api/chat_export');
      if (!res.ok) throw new Error('Failed to export');
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `chat-${(data.session_id || 'session').slice(0,8)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      this.addErrorMessage('Export failed');
    }
  }
}

function initializeChat(sessionId, hasAnyDocument, docs, selectedId) {
  window.chatClient = new BankingChatClient(sessionId, hasAnyDocument, docs, selectedId);
}