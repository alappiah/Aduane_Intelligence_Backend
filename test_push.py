import firebase_admin
from firebase_admin import credentials, messaging

# 1. Initialize (Same as your main.py)
cred = credentials.Certificate("firebase-service-account.json")
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

# 2. Define the Test
def send_test_push(token):
    message = messaging.Message(
        notification=messaging.Notification(
            title="🐍 Python Alert!",
            body="Your backend successfully sent this notification!",
        ),
        token=token,
    )
    
    try:
        response = messaging.send(message)
        print(f"✅ Successfully sent test message: {response}")
    except Exception as e:
        print(f"❌ Error: {e}")

# 3. RUN IT (Replace with your actual token from the DB)
MY_TOKEN = 'eXbO2LRRTs68Kd-QTbAILX:APA91bGp1eblorYqy6Q_mkOGpiZO_zAgX1y259Um4Z-_NhkE-VboFysAOkcuHVF7YLfTQw3SHsUTJgN-ntRrGnkpfK8kSLlftpsdGJHLuMwlpZtDvnvbP0A'
send_test_push(MY_TOKEN)