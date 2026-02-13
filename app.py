import os
import logging
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import eventlet

eventlet.monkey_patch()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-secret-key-change-in-production')
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

# Хранилище: session_id -> {'sid': websocket_sid, 'info': {...}}
active_sessions = {}

def broadcast_sessions():
    """Отправить всем операторам актуальный список сессий с деталями"""
    sessions_data = {
        sess_id: sess['info']
        for sess_id, sess in active_sessions.items()
    }
    socketio.emit('sessions_update', sessions_data)

@app.route('/')
def index():
    """Панель управления оператора"""
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    logger.info(f'Client connected: {request.sid} from {request.remote_addr}')

@socketio.on('register')
def handle_register(data):
    """Регистрация агента с уникальным ID"""
    session_id = data.get('session_id')
    if not session_id:
        emit('error', {'message': 'session_id is required'})
        return

    # Сохраняем информацию о сессии
    active_sessions[session_id] = {
        'sid': request.sid,
        'info': {
            'ip': request.remote_addr,
            'user_agent': request.headers.get('User-Agent', 'Unknown'),
            'data': data.get('info', {})  # дополнительные данные от агента
        }
    }
    emit('registered', {'status': 'ok'})
    broadcast_sessions()
    logger.info(f"Agent registered: {session_id} from {request.remote_addr}")

@socketio.on('disconnect')
def handle_disconnect():
    # Удаляем сессию по websocket sid
    to_remove = None
    for sess_id, sess in list(active_sessions.items()):
        if sess['sid'] == request.sid:
            to_remove = sess_id
            break
    if to_remove:
        del active_sessions[to_remove]
        broadcast_sessions()
        logger.info(f"Agent disconnected: {to_remove}")

@socketio.on('command')
def handle_command(data):
    """Команда от оператора -> пересылается конкретному агенту"""
    target_session = data.get('session_id')
    cmd = data.get('command')
    payload = data.get('payload', '')

    if not target_session or not cmd:
        emit('command_status', {'status': 'error', 'message': 'Missing session_id or command'})
        return

    if target_session not in active_sessions:
        emit('command_status', {'status': 'error', 'message': f'Session {target_session} not found'})
        return

    target_sid = active_sessions[target_session]['sid']
    socketio.emit('command', {'cmd': cmd, 'payload': payload}, room=target_sid)
    emit('command_status', {'status': 'sent', 'session_id': target_session, 'command': cmd})
    logger.info(f"Command '{cmd}' sent to {target_session}")

@socketio.on('command_result')
def handle_command_result(data):
    """Результат выполнения команды от агента"""
    session_id = data.get('session_id')
    result = data.get('result', '')
    socketio.emit('command_result', {'session_id': session_id, 'result': result})
    logger.info(f"Result from {session_id}: {result[:100]}...")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)
