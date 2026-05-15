import os
import json
import sys
import subprocess
import shutil
import zipfile
import logging
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for
from werkzeug.utils import secure_filename
import threading
import time
import psutil

app = Flask(__name__)
app.config['SECRET_KEY'] = 'iftekhar-host-secret-key-2024'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['BOTS_FOLDER'] = 'bots'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max

# ফোল্ডার তৈরি
for folder in [app.config['UPLOAD_FOLDER'], app.config['BOTS_FOLDER'], 'bot_runtime']:
    Path(folder).mkdir(exist_ok=True)

# লগিং সেটআপ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# বট ম্যানেজমেন্ট ক্লাস
class BotManager:
    def __init__(self):
        self.bots = {}
        self.load_bots()
    
    def load_bots(self):
        """সংরক্ষিত বট লোড করা"""
        bots_file = Path('bots_data.json')
        if bots_file.exists():
            with open(bots_file, 'r') as f:
                self.bots = json.load(f)
        else:
            self.bots = {}
    
    def save_bots(self):
        """বট ডাটা সেভ করা"""
        with open('bots_data.json', 'w') as f:
            json.dump(self.bots, f, indent=2)
    
    def add_bot(self, bot_id, bot_name, bot_token, file_path, process_id=None):
        """নতুন বট যোগ করা"""
        self.bots[bot_id] = {
            'id': bot_id,
            'name': bot_name,
            'token': bot_token[:20] + '...' if len(bot_token) > 20 else bot_token,
            'full_token': bot_token,
            'file_path': file_path,
            'process_id': process_id,
            'status': 'stopped',
            'created_at': datetime.now().isoformat(),
            'logs': []
        }
        self.save_bots()
        return True
    
    def remove_bot(self, bot_id):
        """বট ডিলিট করা"""
        if bot_id in self.bots:
            # প্রসেস বন্ধ করা
            self.stop_bot(bot_id)
            # ফাইল ডিলিট
            bot_path = Path(self.bots[bot_id]['file_path'])
            if bot_path.exists():
                shutil.rmtree(bot_path.parent) if bot_path.is_file() else None
            # ডাটা রিমুভ
            del self.bots[bot_id]
            self.save_bots()
            return True
        return False
    
    def start_bot(self, bot_id):
        """বট চালু করা"""
        if bot_id not in self.bots:
            return False, "Bot not found"
        
        bot = self.bots[bot_id]
        if bot['status'] == 'running':
            return False, "Bot already running"
        
        try:
            # বট ফাইল পাথ
            bot_file = Path(bot['file_path'])
            if not bot_file.exists():
                return False, "Bot file not found"
            
            # এনভায়রনমেন্ট ভেরিয়েবল সেট
            env = os.environ.copy()
            env['BOT_TOKEN'] = bot['full_token']
            
            # প্রসেস স্টার্ট
            process = subprocess.Popen(
                [sys.executable, str(bot_file)],
                cwd=bot_file.parent,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            bot['process_id'] = process.pid
            bot['status'] = 'running'
            bot['started_at'] = datetime.now().isoformat()
            self.save_bots()
            
            # লগ মনিটরিং থ্রেড
            self.monitor_logs(bot_id, process)
            
            return True, "Bot started successfully"
        
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def stop_bot(self, bot_id):
        """বট বন্ধ করা"""
        if bot_id not in self.bots:
            return False
        
        bot = self.bots[bot_id]
        if bot['status'] == 'running' and bot.get('process_id'):
            try:
                process = psutil.Process(bot['process_id'])
                process.terminate()
                process.wait(timeout=5)
            except:
                pass
        
        bot['status'] = 'stopped'
        bot['process_id'] = None
        self.save_bots()
        return True
    
    def restart_bot(self, bot_id):
        """বট রিস্টার্ট করা"""
        self.stop_bot(bot_id)
        time.sleep(2)
        return self.start_bot(bot_id)
    
    def get_bot_logs(self, bot_id):
        """বট লগ দেখা"""
        if bot_id in self.bots:
            return self.bots[bot_id].get('logs', [])
        return []
    
    def monitor_logs(self, bot_id, process):
        """লগ মনিটর করা"""
        def monitor():
            for line in iter(process.stdout.readline, ''):
                if line:
                    self.add_log(bot_id, line.strip())
            for line in iter(process.stderr.readline, ''):
                if line:
                    self.add_log(bot_id, f"ERROR: {line.strip()}")
        
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
    
    def add_log(self, bot_id, log_message):
        """লগ অ্যাড করা"""
        if bot_id in self.bots:
            log_entry = {
                'time': datetime.now().isoformat(),
                'message': log_message
            }
            self.bots[bot_id]['logs'].append(log_entry)
            # শুধু শেষ ১০০ লগ রাখা
            if len(self.bots[bot_id]['logs']) > 100:
                self.bots[bot_id]['logs'] = self.bots[bot_id]['logs'][-100:]
            self.save_bots()

bot_manager = BotManager()

# =============== ওয়েব রাউট ===============

@app.route('/')
def index():
    """হোম পেজ"""
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    """ড্যাশবোর্ড"""
    return render_template('dashboard.html')

@app.route('/bot_manager')
def bot_manager_page():
    """বট ম্যানেজার পেজ"""
    return render_template('bot_manager.html')

# =============== API এন্ডপয়েন্ট ===============

@app.route('/api/bots', methods=['GET'])
def get_bots():
    """সব বটের তালিকা"""
    bots_list = []
    for bot_id, bot in bot_manager.bots.items():
        bots_list.append({
            'id': bot['id'],
            'name': bot['name'],
            'status': bot['status'],
            'created_at': bot['created_at']
        })
    return jsonify(bots_list)

@app.route('/api/bots', methods=['POST'])
def upload_bot():
    """বট ফাইল আপলোড"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    bot_name = request.form.get('name', file.filename)
    bot_token = request.form.get('token', '')
    
    if not bot_token:
        return jsonify({'error': 'Bot token is required'}), 400
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    # ফাইল সেভ
    filename = secure_filename(file.filename)
    bot_id = f"bot_{int(time.time())}"
    bot_folder = Path(app.config['BOTS_FOLDER']) / bot_id
    bot_folder.mkdir(exist_ok=True)
    
    file_path = bot_folder / filename
    file.save(file_path)
    
    # জিপ ফাইল আনজিপ
    if filename.endswith('.zip'):
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(bot_folder)
        # প্রধান পাইথন ফাইল খোঁজা
        py_files = list(bot_folder.glob('*.py'))
        if py_files:
            file_path = py_files[0]
    
    # বট অ্যাড
    bot_manager.add_bot(bot_id, bot_name, bot_token, str(file_path))
    
    return jsonify({'success': True, 'bot_id': bot_id})

@app.route('/api/bots/<bot_id>', methods=['DELETE'])
def delete_bot(bot_id):
    """বট ডিলিট"""
    if bot_manager.remove_bot(bot_id):
        return jsonify({'success': True})
    return jsonify({'error': 'Bot not found'}), 404

@app.route('/api/bots/<bot_id>/start', methods=['POST'])
def start_bot(bot_id):
    """বট স্টার্ট"""
    success, message = bot_manager.start_bot(bot_id)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

@app.route('/api/bots/<bot_id>/stop', methods=['POST'])
def stop_bot(bot_id):
    """বট স্টপ"""
    if bot_manager.stop_bot(bot_id):
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to stop bot'}), 400

@app.route('/api/bots/<bot_id>/restart', methods=['POST'])
def restart_bot(bot_id):
    """বট রিস্টার্ট"""
    success, message = bot_manager.restart_bot(bot_id)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

@app.route('/api/bots/<bot_id>/logs', methods=['GET'])
def get_logs(bot_id):
    """বট লগ দেখা"""
    logs = bot_manager.get_bot_logs(bot_id)
    return jsonify(logs)

@app.route('/api/system', methods=['GET'])
def system_info():
    """সিস্টেম ইনফরমেশন"""
    return jsonify({
        'cpu_percent': psutil.cpu_percent(),
        'memory_percent': psutil.virtual_memory().percent,
        'memory_used': psutil.virtual_memory().used,
        'memory_total': psutil.virtual_memory().total,
        'disk_used': psutil.disk_usage('/').used,
        'disk_total': psutil.disk_usage('/').total,
        'bots_count': len(bot_manager.bots),
        'running_bots': sum(1 for b in bot_manager.bots.values() if b['status'] == 'running'),
        'uptime': time.time() - psutil.boot_time()
    })

@app.route('/api/bot_template', methods=['GET'])
def get_bot_template():
    """স্যাম্পল বট টেমপ্লেট"""
    template = '''import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# লগিং সেটআপ
logging.basicConfig(level=logging.INFO)

# টোকেন এনভায়রনমেন্ট থেকে নেওয়া হবে
TOKEN = os.environ.get("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("হ্যালো! আমি আপনার হোস্ট করা বট 🤖")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("কমান্ড সমূহ:\\n/start - শুরু\\n/help - সাহায্য")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"আপনি বলেছেন: {update.message.text}")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    
    print("🤖 বট চালু হচ্ছে...")
    app.run_polling()

if __name__ == "__main__":
    main()
'''
    return jsonify({'template': template})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)