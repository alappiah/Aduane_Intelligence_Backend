from firebase_admin import messaging

def notify_user_of_badge(fcm_token: str, badge_key: str):
    if not fcm_token:
        print("⚠️ No FCM token for user. Skipping push.")
        return

    badge_display_names = {
        "first_steps": "👟 First Steps Taken!",
        "market_navigator": "🛒 Market Navigator",
        "kejetia_king": "👑 Kejetia King"
    }
    
    title = "🏆 Achievement Unlocked!"
    body = f"Congratulations! You've earned the {badge_display_names.get(badge_key, 'New Badge')} badge."

    message = messaging.Message(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        token=fcm_token,
    )

    try:
        response = messaging.send(message)
        print(f"✅ Notification sent: {response}")
    except Exception as e:
        print(f"❌ FCM Error: {e}")




def send_fcm_notification(fcm_token: str, title: str, body: str):
    if not fcm_token:
        print("⚠️ No FCM token for user. Skipping push.")
        return

    message = messaging.Message(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        android=messaging.AndroidConfig(
            priority='high', # Wakes up the screen
            notification=messaging.AndroidNotification(
                channel_id='aduane_channel',
                sound='default',
                default_vibrate_timings=True,
                tag='meal_reminder',
            ),
        ),
        token=fcm_token,
    )

    try:
        response = messaging.send(message)
        print(f"✅ Scheduled Notification sent: {response}")
    except Exception as e:
        print(f"❌ FCM Error: {e}")