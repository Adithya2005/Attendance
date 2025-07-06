import bcrypt
from pymongo import MongoClient

# Connect to MongoDB
client = MongoClient("mongodb+srv://adithya29725:adithya2925@cluster.vywbw.mongodb.net/?retryWrites=true&w=majority&appName=cluster")
db = client['attendance_db']
users_col = db['users']

# Create admin user
username = "admin"
password = "admin123"  # Change to a strong password
name = "Administrator"
role = "admin"

# Check if admin already exists
if users_col.find_one({"username": username}):
    print("Admin already exists.")
else:
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    users_col.insert_one({
        "username": username,
        "password": hashed,
        "name": name,
        "role": role
    })
    print("Admin user created.")
