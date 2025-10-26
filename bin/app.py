from flask import Flask, render_template, request, jsonify, redirect, url_for
import sqlite3
import json
from datetime import datetime
import threading
from collections import defaultdict, deque
import time
import os
import random
import subprocess
import psutil

app = Flask(__name__)

# Debug mode - set to True for detailed logging
debug_on = False

# In-memory storage for real-time data
active_sessions = {}
recent_events = deque(maxlen=100)

# Authorization storage
authorized_sessions = {}  # session_id -> device info
connection_to_session_map = {}  # connection_code -> session_id
session_timeout = 300  # 5 minutes for session to be used

# Dashboard connections storage
dashboard_connections = {}  # session_id -> connection_data

# Websockify process
websockify_process = None
WEBSOCKIFY_PORT = 6080

# Repeater and websockify heartbeat tracking
repeater_last_heartbeat = 0
websockify_last_heartbeat = 0
HEARTBEAT_TIMEOUT = 120  # 2 minutes

# Set static folder
app.static_folder = 'static'

# Debug logging function
def debug_log(message):
    if debug_on:
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"🐛 [{timestamp}] {message}")

# Check if noVNC exists
NOVNC_PATH = os.path.join(app.static_folder, 'noVNC')
if not os.path.exists(NOVNC_PATH):
    print(f"Warning: noVNC not found at {NOVNC_PATH}")

# Initialize SQLite database
def init_db():
    conn = sqlite3.connect('/tmp/repeater_events.db')
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            timestamp INTEGER,
            repeater_pid INTEGER,
            viewer_ip TEXT,
            server_ip TEXT,
            connection_code INTEGER,
            mode INTEGER,
            viewer_table_index INTEGER,
            server_table_index INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS device_auth (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            serial_id TEXT,
            session_id INTEGER,
            client_ip TEXT,
            server_slot TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            used_at DATETIME NULL,
            status TEXT DEFAULT 'pending'
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

def start_websockify():
    """Start single websockify process for all VNC connections"""
    global websockify_process
    
    try:
        # Stop if already running
        stop_websockify()
        
        # Check if UltraVNC repeater is running
        if not is_ultravnc_repeater_running():
            debug_log("Warning: UltraVNC repeater not found on port 5500")
        
        # Get path to websockify
        venv_bin = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'venv', 'bin')
        websockify_cmd = os.path.join(venv_bin, 'websockify')
        
        # Fallback to system websockify
        if not os.path.exists(websockify_cmd):
            websockify_cmd = 'websockify'
        
        # Use 0.0.0.0 to bind to all interfaces, not just localhost
        cmd = [
            websockify_cmd,
            f'0.0.0.0:{WEBSOCKIFY_PORT}',
            f'127.0.0.1:5900',  # Connect to local UltraVNC repeater
            '--web', NOVNC_PATH,
            '--heartbeat', '30',
            '--verbose'
        ]
        
        debug_log(f"Starting websockify: {' '.join(cmd)}")
        
        # Start websockify process
        websockify_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Start heartbeat monitoring for websockify
        threading.Thread(target=monitor_websockify_heartbeat, daemon=True).start()
        
        # Wait and check if started successfully
        time.sleep(3)
        
        if websockify_process.poll() is not None:
            stdout, stderr = websockify_process.communicate()
            debug_log(f"Websockify failed to start. STDOUT: {stdout}")
            debug_log(f"Websockify failed to start. STDERR: {stderr}")
            return False
        
        debug_log(f"✅ Websockify started successfully on port {WEBSOCKIFY_PORT}")
        return True
        
    except Exception as e:
        debug_log(f"❌ Error starting websockify: {e}")
        return False

def monitor_websockify_heartbeat():
    """Monitor websockify process heartbeat"""
    global websockify_last_heartbeat
    
    while True:
        if websockify_process and websockify_process.poll() is None:
            websockify_last_heartbeat = time.time()
        time.sleep(30)

def stop_websockify():
    """Stop websockify process"""
    global websockify_process
    
    if websockify_process:
        try:
            websockify_process.terminate()
            websockify_process.wait(timeout=5)
            debug_log("Websockify stopped successfully")
        except subprocess.TimeoutExpired:
            websockify_process.kill()
            websockify_process.wait()
            debug_log("Websockify killed")
        except Exception as e:
            debug_log(f"Error stopping websockify: {e}")
        finally:
            websockify_process = None

@app.route('/', methods=['GET'])
def handle_root():
    """Handle both dashboard and repeater events"""
    if request.args:  # Если есть GET параметры - это событие от репитера
        debug_log("🔄 Handling repeater event on root path")
        return handle_event()
    else:
        # Если нет параметров - это обычный запрос дашборда
        return redirect(url_for('dashboard_page'))

@app.route('/dashboard')
def dashboard_page():
    """Dashboard with connection cards"""
    debug_log("📊 Dashboard page requested")
    return render_template('dashboard.html')

@app.route('/events')
def events_page():
    """Events log page"""
    debug_log("📋 Events page requested")
    return render_template('events.html')

# API endpoints
@app.route('/api/event', methods=['GET', 'POST'])
def handle_event():
    """Handle incoming events from repeater"""
    global repeater_last_heartbeat
    
    if request.method == 'GET':
        data = request.args
        debug_log(f"🔔 RAW GET EVENT: {dict(data)}")
    else:
        data = request.get_json() or request.form
        debug_log(f"🔔 RAW POST EVENT: {dict(data)}")
    
    try:
        event_data = parse_event_data(data)
        debug_log(f"📋 PARSED EVENT: {event_data}")
        
        # Update repeater heartbeat
        if event_data['event_type'] == 'REPEATER_HEARTBEAT':
            repeater_last_heartbeat = time.time()
            debug_log("❤️ Repeater heartbeat received")
        
        # Сохраняем событие
        store_event(event_data)
        debug_log(f"💾 Event stored in database")
        
        # Обрабатываем событие
        process_event(event_data)
        
        # Выводим текущее состояние после обработки
        debug_log(f"📊 AFTER PROCESSING:")
        debug_log(f"   Active sessions: {len(active_sessions)}")
        debug_log(f"   Dashboard connections: {len(dashboard_connections)}")
        
        return jsonify({'status': 'success', 'message': 'Event processed'})
    
    except Exception as e:
        debug_log(f"❌ Error processing event: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 400

def parse_event_data(data):
    """Parse event data from different formats"""
    event_types = {
        '0': 'VIEWER_CONNECT',      # 0
        '1': 'VIEWER_DISCONNECT',   # 1
        '2': 'SERVER_CONNECT',      # 2
        '3': 'SERVER_DISCONNECT',   # 3
        '4': 'VIEWER_SERVER_SESSION_START',  # 4
        '5': 'VIEWER_SERVER_SESSION_END',    # 5
        '6': 'REPEATER_STARTUP',    # 6
        '7': 'REPEATER_SHUTDOWN',   # 7
        '8': 'REPEATER_HEARTBEAT'   # 8
    }
    
    event_num = data.get('EvNum', '0')
    event_type = event_types.get(event_num, 'UNKNOWN')
    
    debug_log(f"🔍 Parsing event: EvNum={event_num}, type={event_type}")
    
    # Инициализируем переменные
    viewer_ip = ''
    server_ip = ''
    connection_code = int(data.get('Code', 0))
    
    if event_type == 'VIEWER_CONNECT':
        viewer_ip = format_ip(data.get('Ip'))
        debug_log(f"   Viewer IP from 'Ip' parameter: {viewer_ip}")
        
    elif event_type == 'SERVER_CONNECT':
        server_ip = format_ip(data.get('Ip'))
        debug_log(f"   Server IP from 'Ip' parameter: {server_ip}")
        
    elif event_type in ['VIEWER_SERVER_SESSION_START', 'VIEWER_SERVER_SESSION_END']:
        viewer_ip = format_ip(data.get('VwrIp'))
        server_ip = format_ip(data.get('SvrIp'))
        debug_log(f"   Session IPs - Viewer: {viewer_ip}, Server: {server_ip}")
        
    elif event_type in ['VIEWER_DISCONNECT', 'SERVER_DISCONNECT']:
        if event_type == 'VIEWER_DISCONNECT':
            viewer_ip = format_ip(data.get('Ip'))
            debug_log(f"   Viewer disconnect IP from 'Ip': {viewer_ip}")
        else:
            server_ip = format_ip(data.get('Ip'))
            debug_log(f"   Server disconnect IP from 'Ip': {server_ip}")
    
    parsed_data = {
        'event_type': event_type,
        'timestamp': int(data.get('Time', time.time())),
        'repeater_pid': int(data.get('Pid', 0)),
        'viewer_ip': viewer_ip,
        'server_ip': server_ip,
        'connection_code': connection_code,
        'mode': int(data.get('Mode', 0)),
        'viewer_table_index': int(data.get('VwrTblInd') or data.get('TblInd', -1)),
        'server_table_index': int(data.get('SvrTblInd', -1)),
        'max_sessions': int(data.get('MaxSessions', 0))
    }
    
    debug_log(f"   Final parsed data: {parsed_data}")
    return parsed_data

def process_event(event_data):
    """Process event and update dashboard connections"""
    event_type = event_data['event_type']
    connection_code = event_data['connection_code']
    server_ip = event_data['server_ip']
    viewer_ip = event_data['viewer_ip']
    debug_log(f"🔄 PROCESSING: {event_type}, code={connection_code}")
    # Add to recent events
    recent_events.append({
        'timestamp': datetime.fromtimestamp(event_data['timestamp']).strftime('%H:%M:%S'),
        'type': event_type,
        'viewer_ip': viewer_ip,
        'server_ip': server_ip,
        'code': connection_code
    })
    # Update dashboard connections based on event type
    if event_type == 'VIEWER_CONNECT':
        debug_log(f"   👁️ Viewer connected: {viewer_ip}")
        update_viewer_connect(connection_code, viewer_ip)
    elif event_type == 'VIEWER_DISCONNECT':
        debug_log(f"   👁️ Viewer disconnected: {viewer_ip}")
        update_viewer_disconnect(connection_code)
    elif event_type == 'SERVER_CONNECT':
        debug_log(f"   🖥️ Server connected: {server_ip}")
        # Ищем сессию по IP клиента и устанавливаем связь
        debug_log(f"🔍 Looking for session with server_ip: {server_ip}")

        # Ищем сессию по IP клиента
        session_to_link = None
        for session_id, session_data in authorized_sessions.items():
            if session_data['client_ip'] == server_ip and session_data.get('connection_code') is None:
                session_to_link = session_id
                break

        if session_to_link:
            # Устанавливаем связь между connection_code и session_id
            authorized_sessions[session_to_link]['connection_code'] = connection_code
            connection_to_session_map[connection_code] = session_to_link
            debug_log(f"🔗 Linked session {session_to_link} with connection code {connection_code}")

            # Update dashboard connection
            update_server_connect(session_to_link, connection_code, server_ip)
        # СОЗДАЕМ СЕССИЮ ПРИ ПОДКЛЮЧЕНИИ СЕРВЕРА
        active_sessions[connection_code] = {
            'server_ip': server_ip,
            'viewer_ip': '',  # Пока нет клиента
            'mode': event_data['mode'],
            'start_time': event_data['timestamp'],
            'server_index': event_data['server_table_index'],
            'viewer_index': -1,
            'status': 'waiting_for_viewer',
            'session_id': session_to_link
        }
        debug_log(f"✅ SERVER SESSION CREATED: code={connection_code}, server={server_ip}, linked_session={session_to_link}")
    elif event_type == 'SERVER_DISCONNECT':
        debug_log(f"   🖥️ Server disconnected: {server_ip}")

        # Update dashboard connection
        update_server_disconnect(connection_code)

        # Удаляем из маппинга если есть
        if connection_code in connection_to_session_map:
            session_id = connection_to_session_map[connection_code]
            if session_id in authorized_sessions:
                authorized_sessions[session_id]['status'] = 'server_disconnected'
            del connection_to_session_map[connection_code]
            debug_log(f"🔗 Removed session mapping for connection: {connection_code}")

        # Удаляем сессию при отключении сервера
        if connection_code in active_sessions:
            debug_log(f"❌ SERVER SESSION REMOVED: code={connection_code}")
            del active_sessions[connection_code]
        else:
            debug_log(f"⚠️ Server session not found for removal: {connection_code}")
    elif event_type == 'VIEWER_SERVER_SESSION_START':
        debug_log(f"   🔗 Session started: viewer={viewer_ip}, server={server_ip}")

        # ✅ УДАЛЯЕМ АВТОРИЗАЦИОННУЮ СЕССИЮ ПРИ ПОДКЛЮЧЕНИИ КЛИЕНТА
        if connection_code in connection_to_session_map:
            session_id_to_remove = connection_to_session_map[connection_code]
            if remove_auth_session(session_id_to_remove):
                del connection_to_session_map[connection_code]
                debug_log(f"🔗 VNC client connected, removed auth session: {session_id_to_remove} for connection: {connection_code}")
        else:
            debug_log(f"⚠️ No session mapping found for connection code: {connection_code}")

        # Update dashboard connection with viewer info
        update_viewer_connect(connection_code, viewer_ip)

        # Остальная логика обновления сессии...
        if connection_code in active_sessions:
            active_sessions[connection_code].update({
                'viewer_ip': viewer_ip,
                'viewer_index': event_data['viewer_table_index'],
                'status': 'active'
            })
            debug_log(f"🔗 SESSION UPDATED WITH VIEWER: code={connection_code}, viewer={viewer_ip}")
        else:
            active_sessions[connection_code] = {
                'viewer_ip': viewer_ip,
                'server_ip': event_data['server_ip'],
                'mode': event_data['mode'],
                'start_time': event_data['timestamp'],
                'viewer_index': event_data['viewer_table_index'],
                'server_index': event_data['server_table_index'],
                'status': 'active'
            }
            debug_log(f"⚠️ NEW SESSION CREATED (no server): code={connection_code}")
    elif event_type == 'VIEWER_SERVER_SESSION_END':
        debug_log(f"   🔗 Session ended: viewer={viewer_ip}, server={server_ip}")
        # Update dashboard connection
        update_viewer_disconnect(connection_code)
        # НЕМЕДЛЕННО УДАЛЯЕМ КАРТОЧКУ ПРИ ЗАВЕРШЕНИИ СЕССИИ
        remove_dashboard_connection_by_code(connection_code)
        # Сохраняем завершенную сессию
        if connection_code in active_sessions:
            session = active_sessions[connection_code]
            duration = event_data['timestamp'] - session['start_time']
            debug_log(f"📊 SESSION ENDED: code={connection_code}, duration={duration}s")
            del active_sessions[connection_code]
        else:
            debug_log(f"⚠️ Session not found for ending: {connection_code}")

def update_server_connect(session_id, connection_code, server_ip):
    """Update dashboard connection when server connects"""
    debug_log(f"🔄 Updating dashboard connection for session {session_id}")
    if session_id in dashboard_connections:
        dashboard_connections[session_id].update({
            'server_connected': True,
            'server_ip': server_ip,
            'connection_code': connection_code,
            'server_connect_time': time.time()
        })
        debug_log(f"📊 Dashboard updated: server connected for session {session_id}")

def update_server_disconnect(connection_code):
    """Update dashboard connection when server disconnects"""
    # Find session_id by connection_code
    session_id = None
    for sess_id, conn_data in dashboard_connections.items():
        if conn_data.get('connection_code') == connection_code:
            session_id = sess_id
            break
    if session_id:
        dashboard_connections[session_id].update({
            'server_connected': False,
            'server_ip': '',
            'server_disconnect_time': time.time()
        })
        debug_log(f"📊 Dashboard updated: server disconnected for session {session_id}")
    else:
        debug_log(f"❌ No session mapping found for server disconnect code: {connection_code}")

def update_viewer_connect(connection_code, viewer_ip):
    """Update dashboard connection when viewer connects"""
    # Find session_id by connection_code
    session_id = None
    for sess_id, conn_data in dashboard_connections.items():
        if conn_data.get('connection_code') == connection_code:
            session_id = sess_id
            break
    if session_id:
        # Try to get real client IP from websockify
        real_viewer_ip = get_real_viewer_ip(session_id, viewer_ip)
        dashboard_connections[session_id].update({
            'viewer_connected': True,
            'viewer_ip': real_viewer_ip,
            'viewer_connect_time': time.time()
        })
        debug_log(f"📊 Dashboard updated: viewer connected for session {session_id}")

def update_viewer_disconnect(connection_code):
    """Update dashboard connection when viewer disconnects"""
    # Find session_id by connection_code
    session_id = None
    for sess_id, conn_data in dashboard_connections.items():
        if conn_data.get('connection_code') == connection_code:
            session_id = sess_id
            break
    if session_id:
        dashboard_connections[session_id].update({
            'viewer_connected': False,
            'viewer_ip': '',
            'viewer_disconnect_time': time.time()
        })
        debug_log(f"📊 Dashboard updated: viewer disconnected for session {session_id}")
    else:
        debug_log(f"❌ No session mapping found for viewer disconnect code: {connection_code}")

def remove_dashboard_connection_by_code(connection_code):
    """Remove dashboard connection by connection code"""
    debug_log(f"🔄 Looking for dashboard connection to remove: code={connection_code}")
    # Ищем session_id по connection_code
    session_id_to_remove = None
    # Сначала проверяем маппинг
    if connection_code in connection_to_session_map:
        session_id_to_remove = connection_to_session_map[connection_code]
        debug_log(f"✅ Found session mapping for removal: {connection_code} -> {session_id_to_remove}")
    else:
        # Ищем в dashboard_connections по connection_code
        for session_id, conn_data in dashboard_connections.items():
            if conn_data.get('connection_code') == connection_code:
                session_id_to_remove = session_id
                debug_log(f"✅ Found connection in dashboard: {connection_code} -> {session_id_to_remove}")
                break
    if session_id_to_remove and session_id_to_remove in dashboard_connections:
        del dashboard_connections[session_id_to_remove]
        debug_log(f"🗑️ Removed dashboard connection: {session_id_to_remove} (code: {connection_code})")
        # Также удаляем из authorized_sessions если есть
        if session_id_to_remove in authorized_sessions:
            del authorized_sessions[session_id_to_remove]
            debug_log(f"🗑️ Removed auth session: {session_id_to_remove}")
    else:
        debug_log(f"⚠️ No dashboard connection found for removal with code: {connection_code}")

def get_real_viewer_ip(session_id, default_ip):
    """Try to get real viewer IP from websockify"""
    if default_ip == '127.0.0.1':
        return 'Connected via Websockify'
    return default_ip

def format_ip(ip_data):
    """Format IP address from various input formats"""
    if not ip_data:
        debug_log("   IP data is empty")
        return ''
    if isinstance(ip_data, str):
        if '.' in ip_data:
            debug_log(f"   IP is already formatted: {ip_data}")
            return ip_data
        elif ip_data.isdigit():
            result = f"0.0.0.{ip_data}"
            debug_log(f"   Converted numeric IP: {ip_data} -> {result}")
            return result
        debug_log(f"   IP is string but not numeric: {ip_data}")
        return ip_data
    debug_log(f"   IP data is not string: {type(ip_data)} - {ip_data}")
    return str(ip_data)

def store_event(event_data):
    """Store event in database"""
    try:
        conn = sqlite3.connect('/tmp/repeater_events.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO events 
            (event_type, timestamp, repeater_pid, viewer_ip, server_ip, 
             connection_code, mode, viewer_table_index, server_table_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            event_data['event_type'],
            event_data['timestamp'],
            event_data['repeater_pid'],
            event_data['viewer_ip'],
            event_data['server_ip'],
            event_data['connection_code'],
            event_data['mode'],
            event_data['viewer_table_index'],
            event_data['server_table_index']
        ))
        conn.commit()
        conn.close()
        debug_log(f"💾 Event stored in DB: {event_data['event_type']}")
    except Exception as e:
        debug_log(f"❌ Error storing event in DB: {e}")

def remove_auth_session(session_id):
    """Remove authorization session when VNC client connects"""
    if session_id in authorized_sessions:
        debug_log(f"🗑️ Removing auth session: {session_id}")
        # Помечаем сессию как использованную в БД
        conn = sqlite3.connect('/tmp/repeater_events.db')
        c = conn.cursor()
        c.execute('''
            UPDATE device_auth 
            SET used_at = CURRENT_TIMESTAMP, status = 'used'
            WHERE session_id = ?
        ''', (session_id,))
        conn.commit()
        conn.close()
        # Удаляем из памяти
        del authorized_sessions[session_id]
        return True
    return False

# API endpoints for frontend
@app.route('/api/dashboard/connections')
def get_dashboard_connections():
    """Get current connections for dashboard"""
    debug_log(f"📡 API CALL: /api/dashboard/connections")
    # Check service statuses
    current_time = time.time()
    repeater_status = (current_time - repeater_last_heartbeat) < HEARTBEAT_TIMEOUT
    websockify_status = websockify_process and websockify_process.poll() is None
    connections_list = []
    for session_id, conn_data in dashboard_connections.items():
        connections_list.append({
            'session_id': session_id,
            'serial_id': conn_data.get('serial_id', ''),
            'client_ip': conn_data.get('client_ip', ''),
            'server_connected': conn_data.get('server_connected', False),
            'server_ip': conn_data.get('server_ip', ''),
            'viewer_connected': conn_data.get('viewer_connected', False),
            'viewer_ip': conn_data.get('viewer_ip', ''),
            'connection_code': conn_data.get('connection_code'),
            'created_time': conn_data.get('created_time', 0),
            'vnc_url': f"/vnc/{session_id}" if conn_data.get('server_connected') else None
        })
    result = {
        'connections': connections_list,
        'service_status': {
            'repeater': repeater_status,
            'websockify': websockify_status
        }
    }
    debug_log(f"   Returning {len(connections_list)} connections")
    return jsonify(result)

@app.route('/api/dashboard/remove_connection/<int:session_id>', methods=['POST'])
def remove_dashboard_connection(session_id):
    """Manually remove connection from dashboard"""
    if session_id in dashboard_connections:
        del dashboard_connections[session_id]
        debug_log(f"🗑️ Manually removed dashboard connection: {session_id}")
        return jsonify({'status': 'success'})
    else:
        return jsonify({'error': 'Connection not found'}), 404

@app.route('/api/events/list')
def get_events_list():
    """Get events from database"""
    debug_log(f"📡 API CALL: /api/events/list")
    conn = sqlite3.connect('/tmp/repeater_events.db')
    c = conn.cursor()
    c.execute('''
        SELECT * FROM events 
        WHERE event_type != 'REPEATER_HEARTBEAT'
        ORDER BY timestamp DESC 
        LIMIT 50
    ''')
    events = []
    for row in c.fetchall():
        events.append({
            'id': row[0],
            'event_type': row[1],
            'timestamp': datetime.fromtimestamp(row[2]).strftime('%Y-%m-%d %H:%M:%S'),
            'repeater_pid': row[3],
            'viewer_ip': row[4],
            'server_ip': row[5],
            'connection_code': row[6],
            'mode': row[7]
        })
    conn.close()
    debug_log(f"   Returning {len(events)} events from DB")
    return jsonify(events)

# Authorization API endpoint
@app.route('/api/vnc/server/take_slot', methods=['POST'])
def take_slot():
    """Handle device authorization and create dashboard connection"""
    try:
        data = request.get_json()
        if not data or 'serial_id' not in data:
            return jsonify({'error': 'Missing serial_id'}), 400
        serial_id = data['serial_id']
        client_ip = request.remote_addr
        # Generate unique session ID
        session_id = generate_session_id()
        # Get server address
        server_host = get_server_host(request)
        server_slot = f"{server_host}:5500"
        # Store authorization session
        authorized_sessions[session_id] = {
            'serial_id': serial_id,
            'client_ip': client_ip,
            'server_slot': server_slot,
            'created_at': time.time(),
            'status': 'ready',
            'connection_code': None
        }
        # Create dashboard connection
        dashboard_connections[session_id] = {
            'serial_id': serial_id,
            'client_ip': client_ip,
            'server_connected': False,
            'server_ip': '',
            'viewer_connected': False,
            'viewer_ip': '',
            'connection_code': None,
            'created_time': time.time()
        }
        # Store in database for audit
        store_auth_session(serial_id, session_id, client_ip, server_slot)
        debug_log(f"✅ New dashboard connection created: session_id={session_id}, serial_id={serial_id}, client_ip={client_ip}")
        return jsonify({
            'session_id': session_id,
            'server_slot': server_slot
        })
    except Exception as e:
        debug_log(f"❌ Error in take_slot: {e}")
        return jsonify({'error': 'Internal server error'}), 500

def generate_session_id():
    """Generate 10-digit session ID"""
    while True:
        session_id = random.randint(1000000000, 9999999999)
        if session_id not in authorized_sessions:
            return session_id

def get_server_host(request):
    """Get the server host that client should connect to"""
    host = request.headers.get('X-Forwarded-Host') or \
           request.headers.get('Host') or \
           request.host
    if ':' in host:
        host = host.split(':')[0]
    return host

def store_auth_session(serial_id, session_id, client_ip, server_slot):
    """Store authorization session in database"""
    try:
        conn = sqlite3.connect('/tmp/repeater_events.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO device_auth (serial_id, session_id, client_ip, server_slot)
            VALUES (?, ?, ?, ?)
        ''', (serial_id, session_id, client_ip, server_slot))
        conn.commit()
        conn.close()
    except Exception as e:
        debug_log(f"Error storing auth session: {e}")

def cleanup_expired_sessions():
    """Clean up expired authorization sessions and dashboard connections"""
    current_time = time.time()
    expired_sessions = []
    # Clean authorized_sessions
    for session_id, session_data in authorized_sessions.items():
        if current_time - session_data['created_at'] > session_timeout:
            expired_sessions.append(session_id)
    for session_id in expired_sessions:
        if session_id in authorized_sessions:
            del authorized_sessions[session_id]
        if session_id in dashboard_connections:
            del dashboard_connections[session_id]
        debug_log(f"🧹 Cleaned up expired session: {session_id}")

# Background thread for cleaning expired sessions
def session_cleanup_worker():
    while True:
        time.sleep(60)
        cleanup_expired_sessions()

# Start cleanup thread
cleanup_thread = threading.Thread(target=session_cleanup_worker, daemon=True)
cleanup_thread.start()

# noVNC client page
@app.route('/vnc/<int:session_id>')
def novnc_client(session_id):
    """Serve noVNC client for specific session"""
    if session_id not in dashboard_connections:
        return "Session not found or expired", 404
    server_host = get_server_host(request)
    return render_template('novnc.html', 
                         session_id=session_id,
                         websockify_port=WEBSOCKIFY_PORT,
                         server_host=server_host)

# Graceful shutdown
import atexit
import signal

def cleanup():
    """Clean up on shutdown"""
    stop_websockify()

atexit.register(cleanup)

def signal_handler(sig, frame):
    cleanup()
    exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def is_ultravnc_repeater_running():
    """Check if UltraVNC repeater is running on port 5500"""
    try:
        for conn in psutil.net_connections():
            if conn.laddr.port == 5500 and conn.status == 'LISTEN':
                return True
        return False
    except:
        return False

if __name__ == '__main__':
    print("Starting VNC Repeater Event Listener on port 80...")
    print("Dashboard available at: http://0.0.0.0:80/dashboard")
    print("Authorization API: POST /api/vnc/server/take_slot")
    print("noVNC clients available at: http://0.0.0.0/vnc/<session_id>")
    if os.path.exists(NOVNC_PATH):
        print(f"noVNC found at: {NOVNC_PATH}")
    else:
        print(f"Warning: noVNC not found at {NOVNC_PATH}")
    # Initialize repeater heartbeat
    repeater_last_heartbeat = time.time()
    # Start websockify
    if start_websockify():
        print("Websockify proxy ready")
        print(f"🔌 VNC Proxy: ws://0.0.0.0:{WEBSOCKIFY_PORT}/websockify")
        app.run(host='0.0.0.0', port=80, debug=False)
    else:
        print("Failed to start websockify, exiting...")
        exit(1)
