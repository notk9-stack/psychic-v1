import os
import zipfile
import subprocess
import threading
import queue
import time
import json
import shutil
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

# Create necessary folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('extracted', exist_ok=True)
os.makedirs('templates', exist_ok=True)

# Global variables for script management
script_process = None
script_queue = queue.Queue()
script_running = False

# File database
files_db = {}
DB_FILE = 'files_db.json'

def load_db():
    global files_db
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            files_db = json.load(f)

def save_db():
    with open(DB_FILE, 'w') as f:
        json.dump(files_db, f, indent=2)

load_db()

# ============ SCRIPT MANAGEMENT ============

def add_output(message, output_type='info'):
    timestamp = datetime.now().strftime('%H:%M:%S')
    script_queue.put({'timestamp': timestamp, 'message': message, 'type': output_type})

def read_output(pipe, output_type):
    for line in iter(pipe.readline, ''):
        if line:
            add_output(line.strip(), output_type)
    pipe.close()

def run_script():
    global script_process, script_running
    script_path = 'your_script.py'
    
    if not os.path.exists(script_path):
        add_output(f"Error: Script '{script_path}' not found!", 'error')
        script_running = False
        return
    
    try:
        add_output(f"Starting script: {script_path}", 'command')
        script_process = subprocess.Popen(
            ['python', script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        add_output(f"Process started with PID: {script_process.pid}", 'success')
        script_running = True
        
        stdout_thread = threading.Thread(target=read_output, args=(script_process.stdout, 'output'))
        stderr_thread = threading.Thread(target=read_output, args=(script_process.stderr, 'error'))
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()
        
        return_code = script_process.wait()
        if return_code == 0:
            add_output(f"Script completed successfully (exit code: {return_code})", 'success')
        else:
            add_output(f"Script exited with code: {return_code}", 'error')
    except Exception as e:
        add_output(f"Error running script: {str(e)}", 'error')
    finally:
        script_running = False
        script_process = None

def start_script():
    global script_process, script_running
    if script_running:
        return False, "Script is already running"
    thread = threading.Thread(target=run_script)
    thread.daemon = True
    thread.start()
    return True, "Script started successfully"

def stop_script():
    global script_process, script_running
    if not script_running or script_process is None:
        return False, "No script is running"
    try:
        add_output("Stopping script...", 'command')
        script_process.terminate()
        for _ in range(50):
            if script_process.poll() is not None:
                break
            time.sleep(0.1)
        if script_process.poll() is None:
            add_output("Force killing process...", 'warning')
            script_process.kill()
        script_running = False
        add_output("Script stopped", 'success')
        return True, "Script stopped successfully"
    except Exception as e:
        add_output(f"Error stopping script: {str(e)}", 'error')
        return False, f"Error: {str(e)}"

def restart_script():
    add_output("Restarting script...", 'command')
    stop_script()
    time.sleep(1)
    return start_script()

# ============ FILE FUNCTIONS ============

def get_file_icon(filename):
    ext = os.path.splitext(filename)[1].lower()
    icons = {
        '.py': 'fab fa-python', '.zip': 'fas fa-file-archive',
        '.txt': 'fas fa-file-alt', '.pdf': 'fas fa-file-pdf',
        '.jpg': 'fas fa-file-image', '.png': 'fas fa-file-image',
        '.html': 'fab fa-html5', '.css': 'fab fa-css3-alt',
        '.js': 'fab fa-js', '.json': 'fas fa-code',
    }
    return icons.get(ext, 'fas fa-file')

def get_file_color(filename):
    ext = os.path.splitext(filename)[1].lower()
    colors = {
        '.py': '#3776AB', '.zip': '#FF9800', '.txt': '#2196F3',
        '.pdf': '#F44336', '.jpg': '#9C27B0', '.png': '#9C27B0',
        '.html': '#E44D26', '.css': '#264DE4', '.js': '#F7DF1E',
    }
    return colors.get(ext, '#94A3B8')

def extract_zip(filepath, extract_to):
    extracted_files = []
    try:
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
            for file_info in zip_ref.infolist():
                extracted_files.append({
                    'name': file_info.filename,
                    'size': file_info.file_size,
                    'is_dir': file_info.is_dir(),
                })
        return extracted_files
    except Exception as e:
        return {'error': str(e)}

# ============ FLASK ROUTES ============

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/files', methods=['GET'])
def get_files():
    files = []
    for file_id, file_info in files_db.items():
        files.append({
            'id': file_id,
            'name': file_info['name'],
            'size_mb': file_info['size_mb'],
            'is_python': file_info['name'].endswith('.py'),
            'is_zip': file_info['name'].endswith('.zip'),
            'is_main': file_info.get('is_main', False),
            'date': file_info['date'],
            'icon': get_file_icon(file_info['name']),
            'color': get_file_color(file_info['name']),
            'has_extracted': file_info.get('has_extracted', False),
            'extracted_count': file_info.get('extracted_count', 0)
        })
    total_size = sum(f['size_mb'] for f in files_db.values())
    has_main = any(f.get('is_main', False) for f in files_db.values())
    return jsonify({
        'success': True,
        'files': files,
        'total_files': len(files_db),
        'total_size_mb': round(total_size, 2),
        'has_main': has_main
    })

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    filename = secure_filename(file.filename)
    file_id = str(int(datetime.now().timestamp())) + '_' + str(abs(hash(filename)))[-8:]
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_{filename}")
    file.save(filepath)
    
    size_bytes = os.path.getsize(filepath)
    size_mb = round(size_bytes / (1024 * 1024), 2)
    
    file_info = {
        'id': file_id,
        'name': filename,
        'path': filepath,
        'size_mb': size_mb,
        'date': datetime.now().strftime('%Y-%m-%d'),
        'is_main': False,
        'has_extracted': False,
        'extracted_count': 0
    }
    
    if filename.endswith('.zip'):
        extract_dir = os.path.join('extracted', file_id)
        os.makedirs(extract_dir, exist_ok=True)
        extracted_files = extract_zip(filepath, extract_dir)
        if isinstance(extracted_files, list):
            file_info['has_extracted'] = True
            file_info['extracted_path'] = extract_dir
            file_info['extracted_count'] = len([f for f in extracted_files if not f['is_dir']])
            add_output(f"✅ ZIP extracted: {filename} - {file_info['extracted_count']} files", 'success')
    
    files_db[file_id] = file_info
    save_db()
    
    add_output(f"📁 File uploaded: {filename} ({size_mb} MB)", 'info')
    
    return jsonify({'success': True, 'file_id': file_id})

@app.route('/api/set-main/<file_id>', methods=['POST'])
def set_main_file(file_id):
    if file_id in files_db:
        for fid in files_db:
            files_db[fid]['is_main'] = (fid == file_id)
        save_db()
        add_output(f"⭐ Main file set to: {files_db[file_id]['name']}", 'success')
        return jsonify({'success': True, 'message': 'Main file set successfully'})
    return jsonify({'success': False, 'error': 'File not found'}), 404

@app.route('/api/download/<file_id>')
def download_file(file_id):
    if file_id in files_db:
        filepath = files_db[file_id]['path']
        if os.path.exists(filepath):
            return send_file(filepath, as_attachment=True, download_name=files_db[file_id]['name'])
    return jsonify({'error': 'File not found'}), 404

@app.route('/api/delete/<file_id>', methods=['DELETE'])
def delete_file(file_id):
    if file_id in files_db:
        filepath = files_db[file_id]['path']
        if os.path.exists(filepath):
            os.remove(filepath)
        extract_dir = os.path.join('extracted', file_id)
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        del files_db[file_id]
        save_db()
        add_output(f"🗑️ File deleted: {files_db[file_id]['name'] if file_id in files_db else 'Unknown'}", 'warning')
        return jsonify({'success': True})
    return jsonify({'error': 'File not found'}), 404

@app.route('/api/script/start', methods=['POST'])
def api_start_script():
    success, message = start_script()
    return jsonify({'success': success, 'message': message})

@app.route('/api/script/stop', methods=['POST'])
def api_stop_script():
    success, message = stop_script()
    return jsonify({'success': success, 'message': message})

@app.route('/api/script/restart', methods=['POST'])
def api_restart_script():
    success, message = restart_script()
    return jsonify({'success': success, 'message': message})

@app.route('/api/script/status')
def api_script_status():
    return jsonify({'running': script_running, 'pid': script_process.pid if script_process else None})

@app.route('/api/script/output')
def api_script_output():
    outputs = []
    while not script_queue.empty():
        outputs.append(script_queue.get())
    return jsonify({'outputs': outputs})

# Create sample script if it doesn't exist
SAMPLE_SCRIPT = '''#!/usr/bin/env python
import time
import sys

print("=== Iftekhar Hosting Sample Script ===")
print("Script started successfully!")
print("This is a sample Python script running in the background.")

for i in range(10):
    print(f"Processing task {i+1}/10...")
    time.sleep(2)

print("=" * 40)
print("Script completed successfully!")
print("=" * 40)
'''

if not os.path.exists('your_script.py'):
    with open('your_script.py', 'w') as f:
        f.write(SAMPLE_SCRIPT)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)