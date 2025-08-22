from flask import Flask, request, render_template, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room
import os
import logging
from werkzeug.utils import secure_filename
from config import Config
from datetime import datetime
import uuid
import asyncio

# Ensure required directories exist before logging
os.makedirs('logs', exist_ok=True)
os.makedirs('uploads', exist_ok=True)
os.makedirs('static', exist_ok=True)
os.makedirs('data', exist_ok=True)

# Configure logging
try:
    logging.basicConfig(
        level=os.environ.get('LOG_LEVEL', 'INFO'),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/banking_assistant.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    print(f"Warning: Could not set up file logging: {e}")

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

# Initialize SocketIO with threading to avoid async_mode issues
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Import services after app/config set
from services.auth import get_managed_identity_credential
from services.document_intelligence import DocumentIntelligenceService
from services.openai_chat import OpenAIChatService
from services.agents_orchestrator import AgentsOrchestrator

# New data layer: prefer MCP client, fallback to direct SQLite
data_service = None
try:
    from services.mcp_client import MCPBankDataService
    data_service = MCPBankDataService(db_path=Config.SQLITE_DB_PATH)
    logger.info("Using MCPBankDataService (MCP over SQLite).")
except Exception as e:
    logger.warning(f"MCP client not available or failed to start: {e}")
    from services.sqlite_data import SqliteBankDataService
    data_service = SqliteBankDataService(db_path=Config.SQLITE_DB_PATH)
    logger.info("Falling back to SqliteBankDataService (direct SQLite).")

# Initialize Azure services
credential = None
doc_intelligence = None
chat_service = None
agents_orchestrator = None

try:
    logger.info("Initializing Azure Managed Identity credential...")
    credential = get_managed_identity_credential()
    logger.info("Managed identity credential obtained")

    logger.info("Initializing Document Intelligence service...")
    doc_intelligence = DocumentIntelligenceService(credential)
    logger.info("Document Intelligence initialized")

    logger.info("Initializing Azure OpenAI Chat service...")
    chat_service = OpenAIChatService(credential)
    test = chat_service.test_connection()
    if test.get('success'):
        logger.info("Azure OpenAI connection test successful")
    else:
        logger.warning(f"Azure OpenAI connection test failed: {test.get('error')}")
except Exception as e:
    logger.error(f"Service initialization failed: {e}")

try:
    logger.info("Initializing Agents Orchestrator...")
    agents_orchestrator = AgentsOrchestrator(chat_service, data_service, doc_intelligence)
    logger.info("Agents Orchestrator ready")
except Exception as e:
    logger.error(f"Failed to init orchestrator: {e}")

# In-memory sessions (use Redis in production)
chat_sessions = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_session_id():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return session['session_id']

def get_chat_session(session_id):
    if session_id not in chat_sessions:
        chat_sessions[session_id] = {
            'messages': [],
            'documents': [],
            'selected_document_id': None,
            'created_at': datetime.utcnow(),
            'last_activity': datetime.utcnow(),
            'user_id': os.environ.get('DEMO_USER_ID', 'husamhilal')
        }
    return chat_sessions[session_id]

def get_selected_document(chat_session):
    doc_id = chat_session.get('selected_document_id')
    if not doc_id:
        return None
    for d in chat_session.get('documents', []):
        if d.get('id') == doc_id:
            return d
    return None

@app.route('/')
def index():
    session_id = get_session_id()
    cs = get_chat_session(session_id)

    # Resolve display name (prefer DB name; fallback to a friendly default)
    user_display_name = "Husam Hilal"
    try:
        if data_service:
            user_row = data_service.get_user(cs['user_id'])
            user_display_name = (user_row or {}).get('name') or user_display_name
    except Exception:
        pass

    services_status = {
        'document_intelligence': doc_intelligence is not None,
        'chat_service': chat_service is not None,
        'credential': credential is not None,
        'data': data_service is not None
    }
    selected_doc = get_selected_document(cs)
    return render_template('index.html',
                           session_id=session_id,
                           services_status=services_status,
                           documents=[{'id': d['id'], 'filename': d['filename']} for d in cs['documents']],
                           selected_document_id=cs['selected_document_id'],
                           document_summary=selected_doc.get('summary') if selected_doc else None,
                           user_display_name=user_display_name)

# Unified analyze API
@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    if not doc_intelligence:
        return jsonify({'success': False, 'error': 'Document Intelligence service is unavailable'}), 503
    try:
        if 'document' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        file = request.files['document']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'Empty filename'}), 400
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'Invalid file type'}), 400

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        logger.info(f"Analyzing document (API): {filename}")
        results = doc_intelligence.analyze_document(filepath)

        session_id = get_session_id()
        cs = get_chat_session(session_id)
        from uuid import uuid4
        doc_id = str(uuid4())

        summary_text = None
        if chat_service:
            summary = chat_service.summarize(results)
            if summary.get('success'):
                summary_text = summary['summary']

        doc_entry = {
            'id': doc_id,
            'filename': filename,
            'data': results,
            'summary': summary_text,
            'uploaded_at': datetime.utcnow().isoformat()
        }
        cs['documents'].append(doc_entry)
        cs['selected_document_id'] = doc_id
        cs['last_activity'] = datetime.utcnow()

        if os.path.exists(filepath):
            os.remove(filepath)

        socketio.emit('document_processed', {
            'id': doc_id,
            'filename': filename,
            'summary': summary_text or 'Document processed successfully',
            'has_summary': bool(summary_text)
        }, room=session_id)

        return jsonify({'success': True, 'id': doc_id, 'filename': filename, 'summary': summary_text})
    except Exception as e:
        logger.error(f"API analyze error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/documents', methods=['GET'])
def list_documents():
    session_id = get_session_id()
    cs = get_chat_session(session_id)
    docs = [{'id': d['id'], 'filename': d['filename'], 'uploaded_at': d['uploaded_at']} for d in cs['documents']]
    return jsonify({'success': True, 'documents': docs, 'selected_document_id': cs['selected_document_id']})

@app.route('/api/documents/select', methods=['POST'])
def select_document():
    data = request.get_json() or {}
    doc_id = data.get('id')
    session_id = get_session_id()
    cs = get_chat_session(session_id)
    if not doc_id or doc_id not in [d['id'] for d in cs['documents']]:
        return jsonify({'success': False, 'error': 'Invalid document id'}), 400
    cs['selected_document_id'] = doc_id
    cs['last_activity'] = datetime.utcnow()
    return jsonify({'success': True, 'selected_document_id': doc_id})

@app.route('/api/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    session_id = get_session_id()
    cs = get_chat_session(session_id)
    before = len(cs['documents'])
    cs['documents'] = [d for d in cs['documents'] if d['id'] != doc_id]
    if cs['selected_document_id'] == doc_id:
        cs['selected_document_id'] = cs['documents'][0]['id'] if cs['documents'] else None
    after = len(cs['documents'])
    cs['last_activity'] = datetime.utcnow()
    return jsonify({'success': True, 'deleted': before - after, 'selected_document_id': cs['selected_document_id']})

@app.route('/api/chat', methods=['POST'])
def api_chat():
    if not agents_orchestrator:
        return jsonify({'error': 'Agents orchestrator is unavailable'}), 503
    try:
        data = request.get_json() or {}
        message = (data.get('message') or '').strip()
        if not message:
            return jsonify({'error': 'Message is required'}), 400

        session_id = get_session_id()
        cs = get_chat_session(session_id)
        selected_doc = get_selected_document(cs)

        # Persist user message
        cs['messages'].append({'role': 'user', 'content': message, 'timestamp': datetime.utcnow().isoformat()})

        # Try payment confirmation follow-up first
        last_meta = None
        for m in reversed(cs['messages']):
            if m.get('role') == 'assistant' and m.get('meta'):
                last_meta = m['meta']
                break
        followup = asyncio.run(agents_orchestrator.postprocess_followup(cs['user_id'], message, last_meta))
        if followup:
            cs['messages'].append({
                'role': 'assistant',
                'content': followup['message'],
                'timestamp': followup['timestamp'],
                'meta': followup.get('meta', {}),
                'content_type': followup.get('content_type', 'text')
            })
            cs['last_activity'] = datetime.utcnow()
            return jsonify({'success': True, 'response': followup['message'], 'timestamp': followup['timestamp'], 'meta': followup.get('meta', {}), 'content_type': followup.get('content_type', 'text')})

        # Main orchestration
        result = asyncio.run(agents_orchestrator.handle_chat(
            user_id=cs['user_id'],
            message=message,
            document_data=selected_doc['data'] if selected_doc else None
        ))

        if result.get('success'):
            cs['messages'].append({
                'role': 'assistant',
                'content': result['message'],
                'timestamp': result['timestamp'],
                'meta': result.get('meta', {}),
                'content_type': result.get('content_type', 'text')
            })
            cs['last_activity'] = datetime.utcnow()
            return jsonify({
                'success': True,
                'response': result['message'],
                'timestamp': result['timestamp'],
                'meta': result.get('meta', {}),
                'content_type': result.get('content_type', 'text')
            })
        else:
            return jsonify({'success': False, 'error': result.get('error', 'Unknown error')}), 500
    except Exception as e:
        logger.error(f"Chat API error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/clear_chat', methods=['POST'])
def clear_chat():
    try:
        session_id = get_session_id()
        if session_id in chat_sessions:
            chat_sessions[session_id]['messages'] = []
            chat_sessions[session_id]['last_activity'] = datetime.utcnow()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/chat_export', methods=['GET'])
def export_chat():
    try:
        session_id = get_session_id()
        cs = get_chat_session(session_id)
        selected_doc = get_selected_document(cs)
        export_data = {
            'session_id': session_id,
            'selected_document_id': cs['selected_document_id'],
            'documents': [{'id': d['id'], 'filename': d['filename'], 'uploaded_at': d['uploaded_at']} for d in cs['documents']],
            'created_at': cs['created_at'].isoformat(),
            'messages': cs['messages'],
            'document_summary': selected_doc.get('summary') if selected_doc else None
        }
        return jsonify(export_data)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health')
def health():
    status = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'services': {
            'credential': credential is not None,
            'document_intelligence': doc_intelligence is not None,
            'chat_service': chat_service is not None,
            'data': data_service is not None,
            'agents_orchestrator': agents_orchestrator is not None
        }
    }
    if not all(status['services'].values()):
        status['status'] = 'degraded'
    return jsonify(status)

# WebSocket events
@socketio.on('connect')
def ws_connect():
    session_id = get_session_id()
    join_room(session_id)
    emit('connected', {'session_id': session_id})

@socketio.on('disconnect')
def ws_disconnect():
    session_id = session.get('session_id')
    if session_id:
        leave_room(session_id)

if __name__ == '__main__':
    try:
        Config.validate_config()
        socketio.run(app,
                     host='0.0.0.0',
                     port=int(os.environ.get('PORT', 5000)),
                     debug=os.environ.get('FLASK_ENV', 'development') == 'development')
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise