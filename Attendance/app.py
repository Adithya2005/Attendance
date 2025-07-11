import os
import re
import cv2
import numpy as np
import face_recognition
import threading
import bcrypt
from datetime import datetime, timezone, timedelta
import time
from flask import (
    Flask, render_template, redirect, request,
    url_for, flash, Response, send_from_directory, jsonify
)
from flask_login import (
    LoginManager, login_user, login_required,
    logout_user, UserMixin, current_user
)
from pymongo import MongoClient
from bson import ObjectId
from bson.errors import InvalidId
from PIL import Image

# Configuration
MONGO_URI = "mongodb+srv://adithya29725:adithya2925@cluster.vywbw.mongodb.net/?retryWrites=true&w=majority&appName=cluster"
UPLOAD_FOLDER = 'uploads'
SECRET_KEY = 'bK2@uYp$#9zNw!rD7qFvL1x$3eMgJpVt'
ATTENDANCE_WINDOW = 30

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database
client = MongoClient(MONGO_URI)
db = client['attendance_db']
users_col = db['users']
attendance_col = db['attendance']

# Login Manager
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Recognition feedback
attendance_flags = {}
detection_status = ""
last_recognition_status = {"status": "", "timestamp": 0}

# Shared frame and lock
frame_lock = threading.Lock()
shared_frame = None

class User(UserMixin):
    def __init__(self, data):
        self.id = str(data['_id'])
        self.username = data['username']
        self.password = data['password']
        self.role = data.get('role', 'student')
        self.name = data['name']
        self.face_encoding = data.get('face_encoding')

@login_manager.user_loader
def load_user(user_id):
    try:
        u = users_col.find_one({"_id": ObjectId(user_id)})
        return User(u) if u else None
    except (InvalidId, TypeError):
        return None

video_capture = cv2.VideoCapture(0, cv2.CAP_DSHOW)
shared_frame = None
frame_lock = threading.Lock()

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
if not cap.isOpened():
    print("❌ Failed to access webcam")
else:
    print("✅ Webcam is working")
cap.release()

known_faces = []
known_ids = []
if not video_capture.isOpened():
    print("❌ Failed to open video source. Trying alternative.")
    video_capture = cv2.VideoCapture(1)
if not video_capture.isOpened():
    print("❌ Still failed. Exiting.")
    exit(1)
known_faces = []
known_ids = []

def load_known_faces():
    known_faces.clear()
    known_ids.clear()
    for u in users_col.find({"face_encoding": {"$exists": True}}):
        print(f"Loading face encoding for {u['name']}")
        known_faces.append(np.frombuffer(u['face_encoding'], dtype=np.float64))
        known_ids.append(str(u['_id']))
    print(f"✅ Loaded {len(known_faces)} faces")

def face_recognition_loop():
    global last_recognition_status, shared_frame
    while True:
        ret, frame = video_capture.read()
        if not ret:
            continue

        with frame_lock:
            shared_frame = frame.copy()

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        encs = face_recognition.face_encodings(rgb)
        now = datetime.now(timezone.utc)

        detected = False
        for enc in encs:
            matches = face_recognition.compare_faces(known_faces, enc, tolerance=0.5)
            if True in matches:
                uid = known_ids[matches.index(True)]
                recent = attendance_col.find_one({
                    "user_id": uid,
                    "timestamp": {"$gte": now - timedelta(seconds=ATTENDANCE_WINDOW)}
                })
                if not recent:
                    attendance_col.insert_one({
                        "user_id": uid,
                        "timestamp": now
                    })
                    attendance_flags[uid] = True
                    print(f"✅ Attendance marked for {uid} at {now}")
                else:
                    print(f"⏱️ Already marked for {uid}")
                last_recognition_status = {"status": "marked", "timestamp": time.time()}
                detected = True
                break

        if not detected:
            last_recognition_status = {"status": "wrong", "timestamp": time.time()}

        time.sleep(2)

def convert_to_ist(dt):
    return dt + timedelta(hours=5, minutes=30)

@app.route('/')
@login_required
def index():
    start = request.args.get('start')
    end = request.args.get('end')
    filter_query = {}

    if current_user.role == 'student':
        filter_query["user_id"] = current_user.id

    if start and end:
        filter_query["timestamp"] = {
            "$gte": datetime.fromisoformat(start).astimezone(timezone.utc),
            "$lte": datetime.fromisoformat(end).astimezone(timezone.utc)
        }

    records = list(attendance_col.find(filter_query).sort("timestamp", -1))
    user_map = {str(u['_id']): u for u in users_col.find()}

# Filter records whose user_id is present in user_map
    records = [r for r in records if r['user_id'] in user_map]

    record_images = {
    str(r['_id']): re.sub(r'\W+', '', user_map[r['user_id']]['name'].lower()) + ".jpg"
    for r in records
    }

    for r in records:
        r['timestamp'] = convert_to_ist(r['timestamp']).strftime("%Y-%m-%d %H:%M:%S")

    if attendance_flags.get(current_user.id):
        flash("✅ Attendance marked successfully!", "success")
        attendance_flags[current_user.id] = True

    return render_template('index.html', records=records, record_images=record_images, users=user_map)

@app.route('/status')
def recognition_status():
    if last_recognition_status["timestamp"] and time.time() - last_recognition_status["timestamp"] < 3:
        return jsonify({"status": last_recognition_status["status"]})
    return jsonify({"status": ""})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = users_col.find_one({'username': request.form['username']})
        if u and bcrypt.checkpw(request.form['password'].encode(), u['password'].encode()):
            login_user(User(u))
            return redirect(url_for('index'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/enroll', methods=['GET', 'POST'])
@login_required
def enroll():
    students = list(users_col.find({"role": "student"})) if current_user.role == 'admin' else [users_col.find_one({"_id": ObjectId(current_user.id)})]

    if request.method == 'POST':
        uid = request.form.get('user_id', current_user.id)
        file = request.files.get('image')
        if not file:
            flash('Please select an image file.', 'warning')
            return redirect(url_for('enroll'))

        user = users_col.find_one({'_id': ObjectId(uid)})
        safe_name = re.sub(r'\W+', '', user['name'].lower())
        filename = f"{safe_name}.jpg"
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(path)

        img = face_recognition.load_image_file(path)
        encodings = face_recognition.face_encodings(img)
        if not encodings:
            flash('No face detected. Try a different photo.', 'warning')
            return redirect(url_for('enroll'))

        users_col.update_one({'_id': ObjectId(uid)}, {
            "$set": {"face_encoding": encodings[0].astype(np.float64).tobytes()}
        })

        load_known_faces()
        flash(f'Face enrolled for {user["name"]}', 'success')
        return redirect(url_for('enroll'))

    return render_template('enroll.html', students=students)
@app.route('/register', methods=['GET','POST'])
@login_required
def register():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    if request.method == 'POST':
        if users_col.find_one({'username': request.form['username']}):
            flash('Username already exists', 'danger')
            return redirect(url_for('register'))
        pwd = bcrypt.hashpw(request.form['password'].encode(), bcrypt.gensalt()).decode()
        role = request.form.get('role', 'student')
        users_col.insert_one({
            'username': request.form['username'],
            'password': pwd,
            'name': request.form['name'],
            'role': role
        })
        flash('Student registered', 'success')
        return redirect(url_for('register'))
    return render_template('register.html')

@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/video_feed')
@login_required
def video_feed():
    return Response(
        generate_video(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

def generate_video():
    global shared_frame
    while True:
        with frame_lock:
            if shared_frame is None:
                continue
            frame = shared_frame.copy()

        frame = cv2.resize(frame, (640, 480))
        _, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

        time.sleep(0.1)

if __name__ == '__main__':
    load_known_faces()
    threading.Thread(target=face_recognition_loop, daemon=True).start()
    app.run(debug=True)
