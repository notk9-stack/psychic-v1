import os
import sys
import json
import zipfile
import subprocess
import threading
import time
import logging
import shutil
import psutil
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'iftekhar-hosting-secret'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

# ফোল্ডার তৈরি
for folder in ['uploads', 'bots', 'logs']:
    Path(folder).mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# গ্লোবাল ভেরিয়েবল
current_process = None
current_bot_path = None
current_bot_name = None
console_logs = []
system_stats = {
    'cpu_percent': 0,
    'memory_percent': 0,
    'status': 'stopped',
    'bot_name': 'None'
}

def add_log(message, log_type='info'):
    """লগ অ্যাড করা"""
    log_entry = {
        'time': time.strftime('%H:%M:%S'),
        'message': message,
        'type': log_type
    }
    console_logs.append(log_entry)
    if len(console_logs) > 200:
        console_logs.pop(0)
    logger.info(message)

def monitor_system():
    """সিস্টেম মনিটরিং"""
    while True:
        system_stats['cpu_percent'] = psutil.cpu_percent(interval=1)
        system_stats['memory_percent'] = psutil.virtual_memory().percent
        time.sleep(2)

def run_bot_thread(bot_file_path, env_vars):
    """বট রান করার থ্রেড"""
    global current_process, system_stats
    try:
        env = os.environ.copy()
        env.update(env_vars)
        
        current_process = subprocess.Popen(
            [sys.executable, str(bot_file_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            cwd=str(bot_file_path.parent)
        )
        
        add_log(f"🤖 Bot process started with PID: {current_process.pid}", 'success')
        system_stats['status'] = 'running'
        
        for line in iter(current_process.stdout.readline, ''):
            if line:
                add_log(line.strip(), 'output')
        
        current_process.wait()
        system_stats['status'] = 'stopped'
        add_log(f"Bot stopped with code: {current_process.returncode}", 'info')
        
    except Exception as e:
        add_log(f"Error: {str(e)}", 'error')
        system_stats['status'] = 'stopped'

# সিস্টেম মনিটরিং শুরু
monitor_thread = threading.Thread(target=monitor_system, daemon=True)
monitor_thread.start()

# =============== রাউট ===============

@app.route('/')
def dashboard():
    """ড্যাশবোর্ড পেজ"""
    return render_template('dashboard.html')

@app.route('/api/status')
def get_status():
    """API: সিস্টেম স্ট্যাটাস"""
    return jsonify({
        'status': system_stats['status'],
        'cpu': system_stats['cpu_percent'],
        'memory': system_stats['memory_percent'],
        'bot_name': current_bot_name or 'None',
        'logs': console_logs[-50:]
    })

@app.route('/api/upload', methods=['POST'])
def upload_bot():
    """জিপ ফাইল আপলোড ও এক্সট্র্যাক্ট"""
    global current_bot_path, current_bot_name, console_logs
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    # বর্তমান বট বন্ধ করুন
    if current_process and current_process.poll() is None:
        current_process.terminate()
        time.sleep(1)
    
    # ফাইল সেভ
    filename = secure_filename(file.filename)
    upload_path = Path('uploads') / filename
    file.save(upload_path)
    
    # বট ফোল্ডার তৈরি
    bot_name = filename.replace('.zip', '')
    bot_folder = Path('bots') / bot_name
    if bot_folder.exists():
        shutil.rmtree(bot_folder)
    bot_folder.mkdir(parents=True)
    
    # জিপ এক্সট্র্যাক্ট
    try:
        with zipfile.ZipFile(upload_path, 'r') as zip_ref:
            zip_ref.extractall(bot_folder)
        add_log(f"✅ Zip extracted: {filename}", 'success')
    except Exception as e:
        return jsonify({'error': f'Failed to extract zip: {str(e)}'}), 400
    
    # পাইথন ফাইল খোঁজা
    py_files = list(bot_folder.glob('*.py'))
    if not py_files:
        # সাবফোল্ডারেও খোঁজা
        py_files = list(bot_folder.glob('**/*.py'))
    
    if not py_files:
        return jsonify({'error': 'No .py file found in zip'}), 400
    
    current_bot_path = py_files[0]
    current_bot_name = bot_name
    
    add_log(f"📁 Bot loaded: {current_bot_path.name}", 'success')
    add_log(f"📂 Main file: {current_bot_path.name}", 'info')
    
    # ফাইল লিস্ট তৈরি
    files_list = []
    for f in bot_folder.glob('**/*'):
        if f.is_file():
            files_list.append({
                'name': str(f.relative_to(bot_folder)),
                'size': f.stat().st_size,
                'is_py': f.suffix == '.py'
            })
    
    return jsonify({
        'success': True,
        'bot_name': bot_name,
        'main_file': current_bot_path.name,
        'files': files_list
    })

@app.route('/api/files')
def list_files():
    """ফাইল লিস্ট API"""
    if not current_bot_path:
        return jsonify({'files': []})
    
    bot_folder = current_bot_path.parent
    files = []
    for f in sorted(bot_folder.glob('**/*')):
        if f.is_file():
            files.append({
                'name': str(f.relative_to(bot_folder)),
                'size': f.stat().st_size,
                'is_py': f.suffix == '.py'
            })
    
    return jsonify({
        'files': files,
        'current_main': current_bot_path.name,
        'bot_name': current_bot_name
    })

@app.route('/api/file/<path:filename>')
def get_file(filename):
    """ফাইলের কন্টেন্ট দেখা"""
    if not current_bot_path:
        return jsonify({'error': 'No bot loaded'}), 400
    
    bot_folder = current_bot_path.parent
    file_path = bot_folder / filename
    
    # সিকিউরিটি চেক
    if not file_path.exists() or not str(file_path).startswith(str(bot_folder)):
        return jsonify({'error': 'File not found'}), 404
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({
            'filename': filename,
            'content': content,
            'is_main': filename == current_bot_path.name
        })
    except Exception as e:
        return jsonify({'error': f'Cannot read file: {str(e)}'}), 500

@app.route('/api/file/<path:filename>', methods=['POST'])
def save_file(filename):
    """ফাইল সেভ করা"""
    if not current_bot_path:
        return jsonify({'error': 'No bot loaded'}), 400
    
    data = request.get_json()
    content = data.get('content', '')
    
    bot_folder = current_bot_path.parent
    file_path = bot_folder / filename
    
    if not str(file_path).startswith(str(bot_folder)):
        return jsonify({'error': 'Invalid file path'}), 400
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        add_log(f"💾 File saved: {filename}", 'info')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/set_main/<path:filename>', methods=['POST'])
def set_main_file(filename):
    """মেইন ফাইল সেট করা"""
    global current_bot_path
    
    if not current_bot_path:
        return jsonify({'error': 'No bot loaded'}), 400
    
    bot_folder = current_bot_path.parent
    new_main = bot_folder / filename
    
    if not new_main.exists():
        return jsonify({'error': 'File not found'}), 404
    
    current_bot_path = new_main
    add_log(f"🎯 Main file changed to: {filename}", 'success')
    
    return jsonify({'success': True, 'main_file': filename})

@app.route('/api/start', methods=['POST'])
def start_bot():
    """বট স্টার্ট"""
    global current_process, system_stats
    
    if not current_bot_path:
        return jsonify({'error': 'No bot uploaded'}), 400
    
    if current_process and current_process.poll() is None:
        return jsonify({'error': 'Bot already running'}), 400
    
    add_log(f"🚀 Starting bot: {current_bot_path.name}", 'info')
    system_stats['status'] = 'starting'
    
    # বটের নিজস্ব এনভায়রনমেন্ট ভেরিয়েবল (ইউজার যদি টোকেন সেট করতে চায়)
    data = request.get_json() or {}
    env_vars = {}
    
    # বটের কোডে যদি BOT_TOKEN থাকে তাহলে সেটা ব্যবহার করবে
    # ইউজার চাইলে এখানে টোকেন দিতে পারে (optional)
    if data.get('token'):
        env_vars['BOT_TOKEN'] = data['token']
        add_log(f"🔑 Bot token provided", 'info')
    
    thread = threading.Thread(
        target=run_bot_thread,
        args=(current_bot_path, env_vars),
        daemon=True
    )
    thread.start()
    
    return jsonify({'success': True})

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    """বট স্টপ"""
    global current_process, system_stats
    
    if current_process and current_process.poll() is None:
        current_process.terminate()
        add_log("🛑 Bot stopped by user", 'warning')
        system_stats['status'] = 'stopped'
        return jsonify({'success': True})
    
    return jsonify({'error': 'Bot not running'}), 400

@app.route('/api/restart', methods=['POST'])
def restart_bot():
    """বট রিস্টার্ট"""
    data = request.get_json() or {}
    
    if current_process and current_process.poll() is None:
        current_process.terminate()
        time.sleep(2)
    
    return start_bot()

@app.route('/api/delete', methods=['POST'])
def delete_bot():
    """বট ডিলিট"""
    global current_bot_path, current_bot_name, current_process, system_stats
    
    if current_process and current_process.poll() is None:
        current_process.terminate()
        time.sleep(1)
    
    if current_bot_path and current_bot_path.parent.exists():
        shutil.rmtree(current_bot_path.parent)
        add_log(f"🗑️ Bot deleted: {current_bot_name}", 'warning')
    
    current_bot_path = None
    current_bot_name = None
    system_stats['status'] = 'stopped'
    
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)