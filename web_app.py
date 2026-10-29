"""Web interface for the Social Media Friend Management System with Authentication,
Notifications, Bio & Profile management, and Role-Based views.

Features:
- Love Pink Theme (LoveLoop)
- Role-based Authentication (Admin & Normal User)
- Notifications panel (Accepted/Rejected/New requests)
- Reject connection request option
- Normal users see only friends on dashboard (with Discover tab to find new people)
- Admin sees and manages all platform profiles & requests
- Bio & Profile Menu to view/edit personal info
- Functional 'View Profile' modal with bio, mutual friends, and actions
- Real-time Live Sync (1.5s background polling)
"""

import datetime
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, unquote

import dsa


HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8000))
STATE_LOCK = threading.RLock()

# In-memory sessions: token -> {"username": username, "role": role}
SESSIONS = {}


def json_response(handler, payload, status=200):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def error(message, status=400):
    return {"error": message, "status": status}


def read_json(handler):
    try:
        length = int(handler.headers.get("Content-Length", "0"))
        raw = handler.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def save():
    dsa.save_data(silent=True)


def get_session(handler):
    token = handler.headers.get("X-Auth-Token")
    if not token:
        auth_header = handler.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif auth_header:
            token = auth_header.strip()
    if not token:
        parsed = urlparse(handler.path)
        token = parse_qs(parsed.query).get("token", [""])[0]
    if token and token in SESSIONS:
        sess = SESSIONS[token]
        if sess["username"] in dsa.users:
            return sess
    return None


def add_notification(username, text, n_type="info"):
    if username in dsa.users:
        if "notifications" not in dsa.users[username] or not isinstance(dsa.users[username]["notifications"], list):
            dsa.users[username]["notifications"] = []
        dsa.users[username]["notifications"].insert(0, {
            "id": secrets.token_hex(6),
            "text": text,
            "type": n_type,  # 'accepted', 'rejected', 'request', 'info'
            "read": False
        })
        del dsa.users[username]["notifications"][30:]  # keep recent 30


def login_user(data):
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    expected_role = str(data.get("role", "user")).strip().lower()

    if not username or not password:
        return error("Please provide both username and password.")

    if username not in dsa.users:
        return error("Invalid username or password.")

    user = dsa.users[username]
    user_pw = str(user.get("password", "123456"))
    if user_pw != password:
        return error("Invalid username or password.")

    user_role = user.get("role", "admin" if username == "admin" else "user")
    if expected_role == "admin" and user_role != "admin":
        return error("This account does not have Administrator privileges.")

    token = secrets.token_hex(24)
    SESSIONS[token] = {"username": username, "role": user_role}
    return {
        "token": token,
        "username": username,
        "role": user_role,
        "message": f"Welcome back, {username}!"
    }


def register_user(data):
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    age = str(data.get("age", "")).strip()
    city = str(data.get("city", "")).strip()
    bio = str(data.get("bio", "")).strip()

    if not username:
        return error("Username cannot be empty.")
    if len(username) < 2:
        return error("Username must be at least 2 characters long.")
    if username.lower() == "admin":
        return error("Username 'admin' is reserved.")
    if username in dsa.users:
        return error(f"Username '{username}' is already taken.")
    if not password or len(password) < 3:
        return error("Password must be at least 3 characters long.")

    dsa.users[username] = {
        "age": age or None,
        "city": city or None,
        "bio": bio,
        "friends": set(),
        "password": password,
        "role": "user",
        "avatar": {},
        "profile_photo": "",
        "privacy": "public",
        "notifications": [{
            "id": secrets.token_hex(6),
            "text": "🎉 Welcome to LoveLoop! Customize your photo, stories & privacy in 'My Profile'.",
            "type": "info",
            "read": False
        }]
    }
    dsa.action_stack.append(("ADD_USER", username))
    save()

    token = secrets.token_hex(24)
    SESSIONS[token] = {"username": username, "role": "user"}
    return {
        "token": token,
        "username": username,
        "role": "user",
        "message": f"Account created! Welcome to LoveLoop, {username} 💕"
    }


def update_profile(data, session):
    if not session:
        return error("You must be logged in to update your profile.", 401)
    username = session["username"]
    user = dsa.users.get(username)
    if not user:
        return error("User not found.")

    bio = str(data.get("bio", user.get("bio", ""))).strip()
    age = str(data.get("age", user.get("age", ""))).strip()
    city = str(data.get("city", user.get("city", ""))).strip()

    user["bio"] = bio
    user["age"] = age or None
    user["city"] = city or None
    save()
    return {"message": "Profile updated successfully! 💕", "profile": {
        "username": username,
        "age": user["age"],
        "city": user["city"],
        "bio": user["bio"],
        "role": user.get("role", "user"),
        "avatar": user.get("avatar", {})
    }}


def update_avatar(data, session):
    if not session:
        return error("You must be logged in to customize your avatar.", 401)
    username = session["username"]
    user = dsa.users.get(username)
    if not user:
        return error("User not found.")

    avatar_config = data.get("avatar")
    if not isinstance(avatar_config, dict):
        return error("Invalid avatar configuration.")

    user["avatar"] = avatar_config
    save()
    return {"message": "Avatar saved! Looking fresh ✨", "avatar": avatar_config}


def clear_notifications(session):
    if not session:
        return error("Unauthorized", 401)
    username = session["username"]
    if username in dsa.users:
        dsa.users[username]["notifications"] = []
        save()
    return {"message": "Notifications cleared."}


def logout_user(handler):
    token = handler.headers.get("X-Auth-Token")
    if token and token in SESSIONS:
        del SESSIONS[token]
    return {"message": "Logged out successfully."}


def update_profile_photo(data, session):
    if not session:
        return error("Unauthorized", 401)
    username = session["username"]
    user = dsa.users.get(username)
    if not user:
        return error("User not found.")
    photo = data.get("photo", "")
    if not photo or not isinstance(photo, str) or not photo.startswith("data:image/"):
        return error("Invalid photo format.")
    user["profile_photo"] = photo
    save()
    return {"message": "Profile photo updated successfully! 📷", "profile_photo": photo}


def delete_profile_photo(session):
    if not session:
        return error("Unauthorized", 401)
    username = session["username"]
    user = dsa.users.get(username)
    if not user:
        return error("User not found.")
    user["profile_photo"] = ""
    save()
    return {"message": "Profile photo removed! Showing your avatar. ✨"}


def update_privacy(data, session):
    if not session:
        return error("Unauthorized", 401)
    username = session["username"]
    user = dsa.users.get(username)
    if not user:
        return error("User not found.")
    privacy = str(data.get("privacy", "public")).strip().lower()
    if privacy not in ("public", "private"):
        privacy = "public"
    user["privacy"] = privacy
    save()
    return {"message": f"Privacy set to {privacy.capitalize()}! " + ("🔒 Friends only" if privacy == "private" else "🌐 Public to everyone"), "privacy": privacy}


# --- REAL-TIME CHAT CONTROLLER ---
def get_chat(with_user, session):
    if not session:
        return error("Unauthorized", 401)
    current_user = session["username"]
    if not with_user or with_user not in dsa.users:
        return error("User not found.", 404)
    if with_user == current_user:
        return error("You cannot chat with yourself.", 400)

    key = f"{min(current_user, with_user)}:{max(current_user, with_user)}"
    thread = dsa.chats.get(key, [])
    friend_user = dsa.users[with_user]
    is_friend = with_user in dsa.users[current_user].get("friends", set())
    return {
        "with": with_user,
        "is_friend": is_friend,
        "messages": thread,
        "friend_avatar": friend_user.get("avatar", {}),
        "friend_photo": friend_user.get("profile_photo", ""),
        "friend_role": friend_user.get("role", "user")
    }


def send_chat_message(data, session):
    if not session:
        return error("Unauthorized", 401)
    current_user = session["username"]
    to_user = str(data.get("to", "")).strip()
    text = str(data.get("text", "")).strip()
    if not to_user or to_user not in dsa.users:
        return error("Recipient not found.", 404)
    if to_user == current_user:
        return error("You cannot chat with yourself.", 400)
    if not text:
        return error("Message cannot be empty.")

    now = time.time()
    time_str = datetime.datetime.fromtimestamp(now).strftime("%I:%M %p")
    msg = {
        "id": secrets.token_hex(6),
        "from": current_user,
        "to": to_user,
        "text": text,
        "timestamp": now,
        "time_str": time_str
    }
    key = f"{min(current_user, to_user)}:{max(current_user, to_user)}"
    if key not in dsa.chats:
        dsa.chats[key] = []
    dsa.chats[key].append(msg)
    if len(dsa.chats[key]) > 200:
        dsa.chats[key] = dsa.chats[key][-200:]

    add_notification(to_user, f"💬 New message from {current_user}: {text[:35]}", "chat")
    save()
    return {"message": "Sent", "msg": msg}


# --- PHOTO POSTS CONTROLLER ---
def get_posts(session):
    current_user = session.get("username") if session else None
    is_admin = session.get("role") == "admin" if session else False
    my_friends = set(dsa.users[current_user].get("friends", set())) if current_user and current_user in dsa.users else set()

    visible = []
    for p in dsa.posts:
        author = p["author"]
        author_user = dsa.users.get(author, {})
        author_privacy = author_user.get("privacy", "public")

        if author_privacy == "public" or author == current_user or author in my_friends or is_admin:
            visible.append({
                "id": p["id"],
                "author": author,
                "author_avatar": author_user.get("avatar", {}),
                "author_photo": author_user.get("profile_photo", ""),
                "photo": p["photo"],
                "image": p["photo"],
                "caption": p.get("caption", ""),
                "timestamp": p.get("timestamp", 0),
                "time_str": p.get("time_str", ""),
                "likes_count": len(p.get("likes", [])),
                "liked": current_user in p.get("likes", []) if current_user else False,
                "can_delete": is_admin or author == current_user
            })
    return {"posts": visible}


def create_post(data, session):
    if not session:
        return error("Unauthorized", 401)
    current_user = session["username"]
    photo = data.get("photo") or data.get("image") or ""
    caption = str(data.get("caption", "")).strip()
    if not photo or not isinstance(photo, str) or not photo.startswith("data:image/"):
        return error("Please select a valid photo.")

    now = time.time()
    time_str = datetime.datetime.fromtimestamp(now).strftime("%b %d, %I:%M %p")
    post = {
        "id": secrets.token_hex(6),
        "author": current_user,
        "photo": photo,
        "caption": caption,
        "timestamp": now,
        "time_str": time_str,
        "likes": []
    }
    dsa.posts.insert(0, post)
    if len(dsa.posts) > 100:
        dsa.posts = dsa.posts[:100]
    save()
    return {"message": "Photo posted successfully! 📸", "post": post}


def toggle_like_post(data, session):
    if not session:
        return error("Unauthorized", 401)
    current_user = session["username"]
    post_id = str(data.get("post_id", "")).strip()
    for p in dsa.posts:
        if p["id"] == post_id:
            if current_user in p["likes"]:
                p["likes"].remove(current_user)
                liked = False
            else:
                p["likes"].append(current_user)
                liked = True
                if p["author"] != current_user:
                    add_notification(p["author"], f"❤️ {current_user} liked your photo post!", "like")
            save()
            return {"likes_count": len(p["likes"]), "liked": liked}
    return error("Post not found.", 404)


def delete_post(post_id, session):
    if not session:
        return error("Unauthorized", 401)
    current_user = session["username"]
    is_admin = session.get("role") == "admin"
    for idx, p in enumerate(dsa.posts):
        if p["id"] == post_id:
            if p["author"] == current_user or is_admin:
                del dsa.posts[idx]
                save()
                return {"message": "Post deleted successfully."}
            return error("You can only delete your own posts.", 403)
    return error("Post not found.", 404)


# --- STORIES CONTROLLER ---
def get_stories(session):
    now = time.time()
    dsa.stories = [s for s in dsa.stories if s.get("expires_at", 0) > now]

    current_user = session.get("username") if session else None
    is_admin = session.get("role") == "admin" if session else False
    my_friends = set(dsa.users[current_user].get("friends", set())) if current_user and current_user in dsa.users else set()

    stories_by_author = {}
    for s in dsa.stories:
        author = s["author"]
        author_user = dsa.users.get(author, {})
        author_privacy = author_user.get("privacy", "public")

        if author_privacy == "public" or author == current_user or author in my_friends or is_admin:
            if author not in stories_by_author:
                stories_by_author[author] = {
                    "author": author,
                    "author_avatar": author_user.get("avatar", {}),
                    "author_photo": author_user.get("profile_photo", ""),
                    "is_self": author == current_user,
                    "items": []
                }
            media_val = s.get("media") or s.get("photo") or ""
            media_type = s.get("media_type") or ("video" if str(media_val).startswith("data:video/") else "image")
            likes_list = s.get("likes", [])
            views_list = s.get("views", [])
            stories_by_author[author]["items"].append({
                "id": s["id"],
                "author": author,
                "photo": media_val,
                "image": media_val,
                "media": media_val,
                "media_type": media_type,
                "song": s.get("song"),
                "caption": s.get("caption", ""),
                "timestamp": s.get("timestamp", 0),
                "time_str": s.get("time_str", ""),
                "can_delete": is_admin or author == current_user,
                "is_mine": author == current_user,
                "likes_count": len(likes_list),
                "views_count": len(views_list),
                "liked": bool(current_user and current_user in likes_list),
            })
    return {"stories": list(stories_by_author.values())}


def create_story(data, session):
    if not session:
        return error("Unauthorized", 401)
    current_user = session["username"]
    media = data.get("media") or data.get("photo") or data.get("image") or ""
    media_type = data.get("media_type") or ("video" if str(media).startswith("data:video/") else "image")
    caption = str(data.get("caption", "")).strip()
    song = data.get("song") or None

    if not media or not isinstance(media, str) or not (
        media.startswith("data:image/") or 
        media.startswith("data:video/") or 
        media.startswith("http://") or 
        media.startswith("https://")
    ):
        return error("Please select a valid photo or video for your story.")

    now = time.time()
    time_str = datetime.datetime.fromtimestamp(now).strftime("%I:%M %p")
    story = {
        "id": secrets.token_hex(6),
        "author": current_user,
        "photo": media,
        "media": media,
        "media_type": media_type,
        "song": song,
        "caption": caption,
        "timestamp": now,
        "expires_at": now + 86400,
        "time_str": time_str,
        "views": [],
        "likes": []
    }
    dsa.stories.append(story)
    save()
    return {"message": "Story added! Visible for 24 hours ✨", "story": story}


def delete_story(story_id, session):
    if not session:
        return error("Unauthorized", 401)
    current_user = session["username"]
    is_admin = session.get("role") == "admin"
    for idx, s in enumerate(dsa.stories):
        if s["id"] == story_id:
            if s["author"] == current_user or is_admin:
                del dsa.stories[idx]
                save()
                return {"message": "Story deleted."}
            return error("You can only delete your own stories.", 403)
    return error("Story not found.", 404)


def record_story_view(data, session):
    if not session:
        return error("Unauthorized", 401)
    current_user = session["username"]
    story_id = str(data.get("story_id", "")).strip()
    if not story_id:
        return error("Missing story_id", 400)

    for s in dsa.stories:
        if s["id"] == story_id:
            # Authors do not count as viewers of their own stories
            if s["author"] == current_user:
                return {"message": "Author view ignored", "views_count": len(s.get("views", []))}
            views = s.setdefault("views", [])
            already_viewed = False
            for v in views:
                v_name = v.get("username") if isinstance(v, dict) else v
                if v_name == current_user:
                    already_viewed = True
                    break
            if not already_viewed:
                now = time.time()
                views.append({
                    "username": current_user,
                    "timestamp": now,
                    "time_str": datetime.datetime.fromtimestamp(now).strftime("%I:%M %p")
                })
                save()
            return {"message": "View recorded", "views_count": len(views)}
    return error("Story not found", 404)


def toggle_like_story(data, session):
    if not session:
        return error("Unauthorized", 401)
    current_user = session["username"]
    story_id = str(data.get("story_id", "")).strip()
    if not story_id:
        return error("Missing story_id", 400)

    for s in dsa.stories:
        if s["id"] == story_id:
            likes = s.setdefault("likes", [])
            views = s.setdefault("views", [])

            if current_user in likes:
                likes.remove(current_user)
                liked = False
                msg = "Story unliked"
            else:
                likes.append(current_user)
                liked = True
                msg = "Story liked ❤️"
                if s["author"] != current_user:
                    add_notification(s["author"], f"❤️ {current_user} liked your story!", "story_like")

            if s["author"] != current_user:
                already_viewed = False
                for v in views:
                    v_name = v.get("username") if isinstance(v, dict) else v
                    if v_name == current_user:
                        already_viewed = True
                        break
                if not already_viewed:
                    now = time.time()
                    views.append({
                        "username": current_user,
                        "timestamp": now,
                        "time_str": datetime.datetime.fromtimestamp(now).strftime("%I:%M %p")
                    })

            save()
            return {
                "message": msg,
                "liked": liked,
                "likes_count": len(likes),
                "views_count": len(views)
            }
    return error("Story not found", 404)


def get_story_viewers(story_id, session):
    if not session:
        return error("Unauthorized", 401)
    current_user = session["username"]
    is_admin = session.get("role") == "admin"
    if not story_id:
        return error("Missing story_id", 400)

    for s in dsa.stories:
        if s["id"] == story_id:
            if s["author"] != current_user and not is_admin:
                return error("Only the story author can view story viewers.", 403)

            views = s.get("views", [])
            likes = set(s.get("likes", []))
            viewer_list = []

            for v in views:
                v_name = v.get("username") if isinstance(v, dict) else str(v)
                v_time = v.get("time_str", "") if isinstance(v, dict) else ""
                v_ts = v.get("timestamp", 0) if isinstance(v, dict) else 0
                u = dsa.users.get(v_name, {})
                viewer_list.append({
                    "username": v_name,
                    "name": u.get("name", v_name) or v_name,
                    "avatar": u.get("avatar", {}),
                    "profile_photo": u.get("profile_photo", ""),
                    "time_str": v_time,
                    "timestamp": v_ts,
                    "liked": v_name in likes
                })

            viewer_list.sort(key=lambda item: (not item["liked"], -item["timestamp"]))

            return {
                "story_id": story_id,
                "viewers": viewer_list,
                "views_count": len(viewer_list),
                "likes_count": len(likes)
            }
    return error("Story not found", 404)


def state_payload(session=None):
    current_user = session.get("username") if session else None
    current_role = session.get("role") if session else None

    my_friends = set()
    user_notifications = []
    my_profile = None

    if current_user and current_user in dsa.users:
        u = dsa.users[current_user]
        my_friends = set(u.get("friends", set()))
        user_notifications = u.get("notifications", [])
        my_profile = {
            "username": current_user,
            "age": u.get("age"),
            "city": u.get("city"),
            "bio": u.get("bio", ""),
            "role": u.get("role", "user"),
            "friends_count": len(my_friends),
            "avatar": u.get("avatar", {}),
            "profile_photo": u.get("profile_photo", ""),
            "privacy": u.get("privacy", "public"),
        }

    users = []
    for username in sorted(dsa.users, key=str.lower):
        user = dsa.users[username]
        users.append(
            {
                "username": username,
                "age": user.get("age"),
                "city": user.get("city"),
                "bio": user.get("bio", ""),
                "role": user.get("role", "admin" if username == "admin" else "user"),
                "friends": sorted(user.get("friends", set()), key=str.lower),
                "is_friend": username in my_friends,
                "avatar": user.get("avatar", {}),
                "profile_photo": user.get("profile_photo", ""),
                "privacy": user.get("privacy", "public"),
            }
        )

    total_friendships = sum(len(user["friends"]) for user in dsa.users.values()) // 2
    total_users = len(dsa.users)

    all_requests = [{"from": source, "to": target} for source, target in dsa.friend_requests]
    if current_role == "admin":
        visible_requests = all_requests
    elif current_user:
        visible_requests = [r for r in all_requests if r["to"] == current_user or r["from"] == current_user]
    else:
        visible_requests = []

    recent_chats = []
    if current_user:
        for key, thread_msgs in dsa.chats.items():
            parts = key.split(":")
            if len(parts) == 2 and current_user in parts:
                partner = parts[1] if parts[0] == current_user else parts[0]
                if partner in dsa.users and thread_msgs:
                    last_msg = thread_msgs[-1]
                    recent_chats.append({
                        "username": partner,
                        "avatar": dsa.users[partner].get("avatar", {}),
                        "profile_photo": dsa.users[partner].get("profile_photo", ""),
                        "last_message": last_msg.get("text", ""),
                        "last_time": last_msg.get("time_str", ""),
                        "timestamp": last_msg.get("timestamp", 0)
                    })
        recent_chats.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    return {
        "auth": {
            "is_authenticated": bool(session),
            "username": current_user,
            "role": current_role,
            "profile": my_profile
        },
        "notifications": user_notifications,
        "users": users,
        "recent_chats": recent_chats,
        "requests": visible_requests,
        "all_requests_count": len(dsa.friend_requests),
        "recently_viewed": [name for name in dsa.recently_viewed if name in dsa.users],
        "stats": {
            "users": total_users,
            "friendships": total_friendships,
            "average": round(total_friendships * 2 / total_users, 2) if total_users else 0,
            "pending": len(dsa.friend_requests),
        },
    }


def get_profile_details(username, session):
    if username not in dsa.users:
        return error("User not found.", 404)

    target_user = dsa.users[username]
    current_user = session.get("username") if session else None

    # Track recently viewed
    dsa.view_profile(username)
    save()

    friends = set(target_user.get("friends", set()))
    mutual_friends = []
    is_friend = False
    has_pending_outgoing = False
    has_pending_incoming = False

    if current_user and current_user in dsa.users:
        my_friends = set(dsa.users[current_user].get("friends", set()))
        mutual_friends = sorted(list(my_friends & friends), key=str.lower)
        is_friend = username in my_friends
        has_pending_outgoing = (current_user, username) in dsa.friend_requests
        has_pending_incoming = (username, current_user) in dsa.friend_requests

    target_privacy = target_user.get("privacy", "public")
    is_self = current_user == username
    is_admin = session.get("role") == "admin" if session else False
    is_private_locked = (target_privacy == "private") and not is_friend and not is_self and not is_admin

    user_posts = [
        p for p in dsa.posts if p.get("author") == username
    ] if not is_private_locked else []

    return {
        "username": username,
        "age": target_user.get("age") if not is_private_locked else None,
        "city": target_user.get("city") if not is_private_locked else None,
        "bio": target_user.get("bio", "") if not is_private_locked else "",
        "role": target_user.get("role", "admin" if username == "admin" else "user"),
        "friends_count": len(friends),
        "friends": sorted(list(friends), key=str.lower) if not is_private_locked else [],
        "mutual_friends": mutual_friends,
        "is_friend": is_friend,
        "has_pending_outgoing": has_pending_outgoing,
        "has_pending_incoming": has_pending_incoming,
        "avatar": target_user.get("avatar", {}),
        "profile_photo": target_user.get("profile_photo", ""),
        "privacy": target_privacy,
        "is_private_locked": is_private_locked,
        "posts": user_posts
    }


def add_user(data, session):
    if not session or session.get("role") != "admin":
        return error("Only administrators can manually create profiles directly.", 403)
    username = str(data.get("username", "")).strip()
    age = str(data.get("age", "")).strip()
    city = str(data.get("city", "")).strip()
    bio = str(data.get("bio", "")).strip()
    password = str(data.get("password", "123456")).strip() or "123456"
    role = str(data.get("role", "user")).strip()
    if not username:
        return error("Username cannot be empty.")
    if username in dsa.users:
        return error(f"User '{username}' already exists.")
    dsa.users[username] = {
        "age": age or None,
        "city": city or None,
        "bio": bio,
        "friends": set(),
        "password": password,
        "role": role,
        "notifications": []
    }
    dsa.action_stack.append(("ADD_USER", username))
    save()
    return {"message": f"User '{username}' added successfully."}


def delete_user(username, session):
    if not session or session.get("role") != "admin":
        return error("Only administrators can delete profiles.", 403)

    username = str(username or "").strip()
    if not username:
        return error("Username cannot be empty.")

    # Match exact or case-insensitive
    target_username = None
    if username in dsa.users:
        target_username = username
    else:
        for u in dsa.users:
            if u.lower() == username.lower():
                target_username = u
                break

    if not target_username:
        return error(f"User '{username}' was not found.")

    username = target_username
    if username.lower() == "admin":
        return error("The main administrator account cannot be deleted.")

    removed_user = dsa.users[username]

    # 1. Remove from all friends' connection lists
    for friend in list(removed_user.get("friends", set())):
        if friend in dsa.users:
            dsa.users[friend]["friends"].discard(username)

    # 2. Delete user profile from users dictionary
    del dsa.users[username]

    # 3. Clean up pending friend requests
    from collections import deque
    dsa.friend_requests = deque([r for r in dsa.friend_requests if r[0] != username and r[1] != username])

    # 4. Clean up recently viewed
    dsa.recently_viewed[:] = [name for name in dsa.recently_viewed if name != username]

    # 5. Clean up all posts authored by this user, and remove user from post likes
    dsa.posts = [p for p in dsa.posts if p.get("author") != username]
    for p in dsa.posts:
        if "likes" in p and isinstance(p["likes"], list):
            p["likes"] = [u for u in p["likes"] if u != username]

    # 6. Clean up all stories authored by this user, and remove user from story likes & viewers
    dsa.stories = [s for s in dsa.stories if s.get("author") != username]
    for s in dsa.stories:
        if "likes" in s and isinstance(s["likes"], list):
            s["likes"] = [u for u in s["likes"] if u != username]
        if "viewers" in s and isinstance(s["viewers"], list):
            s["viewers"] = [u for u in s["viewers"] if u != username]

    # 7. Clean up all chat threads involving this user
    for key in list(dsa.chats.keys()):
        parts = key.split(":")
        if username in parts or any(p.lower() == username.lower() for p in parts):
            del dsa.chats[key]

    # 8. Clean up notifications referencing this user from other users' notification lists
    for u in dsa.users.values():
        u["notifications"] = [
            n for n in u.get("notifications", [])
            if username not in n.get("text", "")
        ]

    # 9. Invalidate any active session tokens for this user
    for tok, sess in list(SESSIONS.items()):
        if sess.get("username") == username or sess.get("username", "").lower() == username.lower():
            del SESSIONS[tok]

    # 10. Record undo action
    dsa.action_stack.append(("DELETE_USER", (username, removed_user)))

    # 11. Persist changes to disk immediately
    save()
    return {"message": f"User '{username}' deleted successfully."}


def change_friendship(data, adding, session):
    if not session:
        return error("You must be logged in.", 401)
    user_a = str(data.get("user_a", "")).strip()
    user_b = str(data.get("user_b", "")).strip()

    if session["role"] != "admin":
        if not adding and (user_a != session["username"] and user_b != session["username"]):
            return error("You can only remove friendships connected to your own account.", 403)
        if adding and session["role"] != "admin":
            return error("Direct connecting is reserved for Admin. Please use 'Send Request'.", 403)

    if user_a not in dsa.users or user_b not in dsa.users:
        return error("Both users must exist.")
    if user_a == user_b:
        return error("A user cannot be friends with themselves.")

    are_friends = user_b in dsa.users[user_a]["friends"]
    if adding and are_friends:
        return error("These users are already friends.")
    if not adding and not are_friends:
        return error("These users are not friends.")

    if adding:
        dsa.users[user_a]["friends"].add(user_b)
        dsa.users[user_b]["friends"].add(user_a)
        action = "ADD_FRIEND"
        message = f"{user_a} and {user_b} are now friends."
        add_notification(user_a, f"💖 You and {user_b} are now connected!", "accepted")
        add_notification(user_b, f"💖 You and {user_a} are now connected!", "accepted")
    else:
        dsa.users[user_a]["friends"].discard(user_b)
        dsa.users[user_b]["friends"].discard(user_a)
        action = "REMOVE_FRIEND"
        message = f"Friendship between {user_a} and {user_b} removed."

    dsa.action_stack.append((action, (user_a, user_b)))
    save()
    return {"message": message}


def send_request(data, session):
    if not session:
        return error("You must be logged in to send connection requests.", 401)

    target = str(data.get("to", "")).strip()
    if session["role"] == "admin":
        source = str(data.get("from", session["username"])).strip()
    else:
        source = session["username"]

    if source not in dsa.users or target not in dsa.users:
        return error("Both users must exist.")
    if source == target:
        return error("You cannot send a connection request to yourself.")
    if target in dsa.users[source]["friends"]:
        return error(f"You and {target} are already connected!")
    if (source, target) in dsa.friend_requests:
        return error("This connection request is already pending.")

    dsa.friend_requests.append((source, target))
    add_notification(target, f"💌 {source} sent you a connection request!", "request")
    save()
    return {"message": f"Connection request sent to {target}! 💕"}


def accept_request(data, session):
    if not session:
        return error("You must be logged in to accept connection requests.", 401)

    source = str(data.get("from", "")).strip()
    target = str(data.get("to", "")).strip()

    if session["role"] != "admin" and target != session["username"]:
        return error("You can only accept requests sent to your own profile.", 403)

    matching = None
    for pair in list(dsa.friend_requests):
        if pair[0] == source and pair[1] == target:
            matching = pair
            dsa.friend_requests.remove(pair)
            break

    if not matching:
        return error("This request is no longer pending.")

    if source not in dsa.users or target not in dsa.users:
        save()
        return {"message": "Request cleared because a user no longer exists."}

    dsa.users[source]["friends"].add(target)
    dsa.users[target]["friends"].add(source)
    dsa.action_stack.append(("ADD_FRIEND", (source, target)))

    # Notifications
    add_notification(source, f"💖 {target} accepted your connection request! You are now friends.", "accepted")
    add_notification(target, f"💖 You accepted {source}'s request! You are now friends.", "accepted")
    save()
    return {"message": f"You and {source} are now connected! 💕"}


def reject_request(data, session):
    if not session:
        return error("You must be logged in to reject connection requests.", 401)

    source = str(data.get("from", "")).strip()
    target = str(data.get("to", "")).strip()

    if session["role"] != "admin" and target != session["username"]:
        return error("You can only reject requests sent to your own profile.", 403)

    matching = None
    for pair in list(dsa.friend_requests):
        if pair[0] == source and pair[1] == target:
            matching = pair
            dsa.friend_requests.remove(pair)
            break

    if not matching:
        return error("This request is no longer pending.")

    # Notify sender that request was declined
    add_notification(source, f"💔 {target} declined your connection request.", "rejected")
    save()
    return {"message": f"Connection request from {source} was declined."}


def process_next_request(session):
    if not session or session.get("role") != "admin":
        return error("Only administrators can process the global queue directly.", 403)
    if not dsa.friend_requests:
        return error("No pending friend requests in the queue.")

    source, target = dsa.friend_requests.popleft()
    if source not in dsa.users or target not in dsa.users:
        save()
        return {"message": "Request skipped because a user no longer exists."}
    if source == target:
        save()
        return {"message": "Request skipped because users cannot be friends with themselves."}
    if target in dsa.users[source]["friends"]:
        save()
        return {"message": "Request skipped because these users are already friends."}

    dsa.users[source]["friends"].add(target)
    dsa.users[target]["friends"].add(source)
    dsa.action_stack.append(("ADD_FRIEND", (source, target)))
    add_notification(source, f"💖 Admin approved connection with {target}!", "accepted")
    add_notification(target, f"💖 Admin approved connection with {source}!", "accepted")
    save()
    return {"message": f"Approved! {source} and {target} are now friends."}


def recommendations(username):
    if username not in dsa.users:
        return []
    direct = dsa.users[username]["friends"]
    scores = {}
    for friend in direct:
        if friend not in dsa.users:
            continue
        for friend_of_friend in dsa.users[friend]["friends"]:
            if friend_of_friend != username and friend_of_friend not in direct:
                scores[friend_of_friend] = scores.get(friend_of_friend, 0) + 1
    return [
        {"username": name, "score": score}
        for name, score in sorted(scores.items(), key=lambda item: (-item[1], item[0].lower()))[:5]
    ]


def undo(session):
    if not session or session.get("role") != "admin":
        return error("Only administrators can undo system actions.", 403)
    if not dsa.action_stack:
        return error("There are no actions to undo.")
    action_type, data = dsa.action_stack.pop()
    try:
        if action_type == "ADD_USER":
            dsa.users.pop(data, None)
        elif action_type == "DELETE_USER":
            username, user_data = data
            dsa.users[username] = user_data
            for friend in user_data["friends"]:
                if friend in dsa.users:
                    dsa.users[friend]["friends"].add(username)
        elif action_type == "ADD_FRIEND":
            user_a, user_b = data
            if user_a in dsa.users and user_b in dsa.users:
                dsa.users[user_a]["friends"].discard(user_b)
                dsa.users[user_b]["friends"].discard(user_a)
        elif action_type == "REMOVE_FRIEND":
            user_a, user_b = data
            if user_a in dsa.users and user_b in dsa.users:
                dsa.users[user_a]["friends"].add(user_b)
                dsa.users[user_b]["friends"].add(user_a)
        else:
            return error("Unknown action cannot be undone.")
    except KeyError:
        return error("This action can no longer be undone safely.")
    save()
    return {"message": "Last action undone."}


class AppHandler(BaseHTTPRequestHandler):
    def log_message(self, format_string, *args):
        return

    def send_html(self):
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        session = get_session(self)
        if parsed.path == "/":
            self.send_html()
            return
        if parsed.path == "/api/state":
            with STATE_LOCK:
                json_response(self, state_payload(session))
            return
        if parsed.path == "/api/profile":
            user_to_get = parse_qs(parsed.query).get("user", [""])[0]
            if not user_to_get and session:
                user_to_get = session["username"]
            with STATE_LOCK:
                json_response(self, get_profile_details(user_to_get, session))
            return
        if parsed.path == "/api/recommendations":
            username = parse_qs(parsed.query).get("user", [""])[0]
            if not username and session:
                username = session["username"]
            with STATE_LOCK:
                json_response(self, {"recommendations": recommendations(username)})
            return
        if parsed.path == "/api/chat":
            with_user = parse_qs(parsed.query).get("with", [""])[0]
            with STATE_LOCK:
                result = get_chat(with_user, session)
            json_response(self, result, result.get("status", 200))
            return
        if parsed.path == "/api/posts":
            with STATE_LOCK:
                result = get_posts(session)
            json_response(self, result, result.get("status", 200))
            return
        if parsed.path == "/api/stories":
            with STATE_LOCK:
                result = get_stories(session)
            json_response(self, result, result.get("status", 200))
            return
        if parsed.path == "/api/stories/viewers":
            story_id = parse_qs(parsed.query).get("story_id", [""])[0]
            with STATE_LOCK:
                result = get_story_viewers(story_id, session)
            json_response(self, result, result.get("status", 200))
            return
        json_response(self, error("Not found.", 404), 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        data = read_json(self)
        session = get_session(self)
        with STATE_LOCK:
            if parsed.path == "/api/login":
                result = login_user(data)
            elif parsed.path == "/api/register":
                result = register_user(data)
            elif parsed.path == "/api/logout":
                result = logout_user(self)
            elif parsed.path == "/api/profile":
                result = update_profile(data, session)
            elif parsed.path == "/api/profile/avatar":
                result = update_avatar(data, session)
            elif parsed.path == "/api/profile/photo":
                result = update_profile_photo(data, session)
            elif parsed.path == "/api/profile/privacy":
                result = update_privacy(data, session)
            elif parsed.path == "/api/chat":
                result = send_chat_message(data, session)
            elif parsed.path == "/api/posts":
                result = create_post(data, session)
            elif parsed.path == "/api/posts/like":
                result = toggle_like_post(data, session)
            elif parsed.path == "/api/stories":
                result = create_story(data, session)
            elif parsed.path == "/api/stories/view":
                result = record_story_view(data, session)
            elif parsed.path == "/api/stories/like":
                result = toggle_like_story(data, session)
            elif parsed.path == "/api/notifications/clear":
                result = clear_notifications(session)
            elif parsed.path == "/api/users":
                result = add_user(data, session)
            elif parsed.path == "/api/friends":
                result = change_friendship(data, adding=True, session=session)
            elif parsed.path == "/api/requests":
                result = send_request(data, session)
            elif parsed.path == "/api/requests/accept":
                result = accept_request(data, session)
            elif parsed.path == "/api/requests/reject":
                result = reject_request(data, session)
            elif parsed.path == "/api/requests/process":
                result = process_next_request(session)
            elif parsed.path == "/api/undo":
                result = undo(session)
            elif parsed.path == "/api/view":
                username = str(data.get("username", "")).strip()
                result = get_profile_details(username, session)
            else:
                result = error("Not found.", 404)
        json_response(self, result, result.get("status", 200))

    def do_DELETE(self):
        parsed = urlparse(self.path)
        data = read_json(self)
        session = get_session(self)
        with STATE_LOCK:
            if parsed.path.startswith("/api/users"):
                username = ""
                if parsed.path.startswith("/api/users/"):
                    username = parsed.path.removeprefix("/api/users/")
                if not username:
                    username = str(data.get("username", "")).strip() or parse_qs(parsed.query).get("username", [""])[0]
                username = unquote(username).strip()
                result = delete_user(username, session)
            elif parsed.path == "/api/friends":
                result = change_friendship(data, adding=False, session=session)
            elif parsed.path == "/api/profile/photo":
                result = delete_profile_photo(session)
            elif parsed.path.startswith("/api/posts/"):
                post_id = parsed.path.removeprefix("/api/posts/")
                result = delete_post(post_id, session)
            elif parsed.path.startswith("/api/stories/"):
                story_id = parsed.path.removeprefix("/api/stories/")
                result = delete_story(story_id, session)
            elif parsed.path == "/api/stories":
                story_id = parse_qs(parsed.query).get("id", [""])[0] or data.get("id", "")
                result = delete_story(story_id, session)
            else:
                result = error("Not found.", 404)
        json_response(self, result, result.get("status", 200))


PAGE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LoveLoop · Connections & Sparks</title>
  <style>
    :root {
      --bg: #fff7fb;
      --ink: #391d2d;
      --muted: #977585;
      --line: #f4dce7;
      --card: #ffffff;
      --purple: #e74f83;
      --purple-dark: #bd3265;
      --teal: #d95c92;
      --rose: #ef6a8a;
      --shadow: 0 18px 45px rgba(169, 67, 108, .12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--bg);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    button, input, select, textarea { font: inherit; }
    button { cursor: pointer; border: 0; }
    .shell { max-width: 1380px; margin: auto; padding: 26px 28px 48px; }

    /* Topbar */
    .topbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 26px; }
    .brand { display: flex; align-items: center; gap: 12px; }
    .logo {
      width: 44px; height: 44px; display: grid; place-items: center;
      color: #fff; border-radius: 14px;
      background: linear-gradient(135deg, #ff8eae, #dd3e77);
      box-shadow: 0 10px 22px rgba(221, 62, 119, .28); font-size: 23px;
    }
    .brand h1 { font-size: 22px; margin: 0; letter-spacing: -.4px; }
    .brand p { margin: 3px 0 0; color: var(--muted); font-size: 12px; }
    .top-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

    /* Badges & Pills */
    .live-pill {
      display: inline-flex; align-items: center; gap: 7px;
      font-size: 12px; font-weight: 700; color: #bd3265;
      background: #ffe5ef; padding: 6px 13px; border-radius: 20px; border: 1px solid #ffd0e2;
    }
    .live-dot {
      width: 8px; height: 8px; border-radius: 50%; background: #10b981;
      box-shadow: 0 0 0 3px rgba(16, 185, 129, .25); animation: pulse 1.8s infinite;
    }
    @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .35; transform: scale(1.25); } }
    .user-pill {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 800;
      color: var(--purple-dark); background: #fff0f6; border: 1px solid var(--line); cursor: pointer;
      transition: .15s ease;
    }
    .user-pill:hover { background: #ffe4ee; }
    .admin-pill {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 800;
      color: #92400e; background: #fef3c7; border: 1px solid #fde68a; cursor: pointer;
    }

    /* Notification Bell Button */
    .notif-btn {
      position: relative; padding: 7px 14px; border-radius: 20px; font-weight: 700;
      font-size: 12px; color: var(--purple-dark); background: #fff0f6; border: 1px solid var(--line);
      display: inline-flex; align-items: center; gap: 6px;
    }
    .notif-btn:hover { background: #ffe4ee; }
    .notif-count {
      padding: 2px 6px; border-radius: 10px; font-size: 10px; font-weight: 800;
      background: #dd2476; color: #fff; display: inline-block;
    }

    /* Buttons */
    .btn { padding: 11px 18px; border-radius: 11px; font-weight: 700; transition: .18s ease; display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
    .btn:hover { transform: translateY(-1px); }
    .btn-primary { color: #fff; background: linear-gradient(135deg, #ff6584, #dd2476); box-shadow: 0 8px 18px rgba(221, 62, 119, .25); }
    .btn-soft { color: var(--purple-dark); background: #ffe9f1; }
    .btn-danger { color: #c43e61; background: #fff0f4; }

    /* Hero Banner */
    .hero {
      position: relative; overflow: hidden; color: #fff; padding: 32px 38px; border-radius: 25px;
      background: linear-gradient(110deg, #a82d5c 0%, #e64c82 53%, #ff93b4 100%);
      box-shadow: var(--shadow); margin-bottom: 22px;
    }
    .hero:after {
      content: "♡"; position: absolute; right: 6%; top: -40px;
      color: rgba(255, 255, 255, .14); font-size: 270px; line-height: 1; transform: rotate(-12deg); pointer-events: none;
    }
    .hero h2 { position: relative; z-index: 1; margin: 0 0 8px; max-width: 650px; font-size: 30px; letter-spacing: -1px; }
    .hero p { position: relative; z-index: 1; margin: 0; max-width: 610px; line-height: 1.65; color: #ffe8f0; }

    /* Stats Grid */
    .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 20px 0; }
    .stat, .card { background: var(--card); border: 1px solid var(--line); box-shadow: var(--shadow); border-radius: 18px; }
    .stat { padding: 18px 20px; }
    .stat small { color: var(--muted); font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .6px; }
    .stat strong { display: block; margin-top: 8px; font-size: 27px; letter-spacing: -1px; }

    /* Layout */
    .layout { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(330px, .85fr); gap: 22px; align-items: start; }
    .card { padding: 22px; }
    .card-head { display: flex; justify-content: space-between; align-items: center; gap: 14px; margin-bottom: 18px; }
    .card h3 { margin: 0; font-size: 18px; letter-spacing: -.3px; }
    .eyebrow { color: var(--purple); font-size: 11px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase; }

    /* View Switcher Tabs (Friends vs Discover) */
    .tab-pills { display: flex; background: #fff0f5; padding: 4px; border-radius: 12px; margin-bottom: 16px; gap: 4px; }
    .tab-pill {
      flex: 1; padding: 8px 12px; border-radius: 9px; font-size: 13px; font-weight: 800;
      color: var(--muted); background: transparent; transition: .15s ease;
    }
    .tab-pill.active { background: #fff; color: var(--purple-dark); box-shadow: 0 4px 10px rgba(189,50,101,.12); }

    /* Forms & Inputs */
    .search { width: 200px; padding: 9px 12px; border: 1px solid var(--line); border-radius: 10px; outline: 0; background: #fffafd; }
    .search:focus, input:focus, select:focus, textarea:focus { border-color: #ed78a2; box-shadow: 0 0 0 3px #ffe9f1; }
    .stack { display: grid; gap: 18px; }
    .field { display: grid; gap: 7px; margin-bottom: 12px; }
    label { color: #566078; font-size: 12px; font-weight: 700; }
    input, select, textarea { width: 100%; padding: 11px 12px; color: var(--ink); border: 1px solid var(--line); border-radius: 10px; outline: 0; background: #fffcfd; }
    .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .form-actions { display: flex; gap: 8px; align-items: center; }

    /* User Grid */
    .user-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px; }
    .user-card {
      position: relative; overflow: hidden; padding: 16px; border: 1px solid var(--line); border-radius: 14px;
      background: linear-gradient(180deg, #fff, #fff8fb);
    }
    .user-card:before { content: ""; position: absolute; width: 75px; height: 75px; right: -25px; top: -26px; border-radius: 50%; background: #fff0f5; }
    .user-top { display: flex; align-items: center; gap: 11px; position: relative; }
    .avatar {
      width: 44px; height: 44px; display: grid; place-items: center; flex: none; border-radius: 50%;
      border: 2px solid #ffd4e5; box-shadow: 0 4px 12px rgba(221, 62, 119, .15); overflow: hidden;
      background: #ffe4ee; position: relative;
    }
    .avatar svg { width: 100%; height: 100%; display: block; border-radius: 50%; }
    .avatar-preview-box {
      width: 108px; height: 108px; border-radius: 50%; border: 4px solid #ff8eae;
      box-shadow: 0 10px 28px rgba(221,62,119,.3); margin: 0 auto 12px; overflow: hidden;
      background: #ffe4ee; animation: avatarGlow 2.5s infinite alternate;
    }
    @keyframes avatarGlow {
      from { box-shadow: 0 8px 20px rgba(221,62,119,.2); }
      to { box-shadow: 0 14px 32px rgba(221,62,119,.42); }
    }
    .avatar-preview-box svg { width: 100%; height: 100%; display: block; border-radius: 50%; }

    /* Avatar Studio Controls */
    .studio-group { margin-bottom: 16px; text-align: left; }
    .studio-title { font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .5px; color: var(--purple-dark); margin-bottom: 8px; }
    .swatch-row { display: flex; gap: 8px; flex-wrap: wrap; }
    .swatch-btn {
      width: 32px; height: 32px; border-radius: 50%; border: 2px solid #fff; cursor: pointer;
      box-shadow: 0 2px 6px rgba(0,0,0,.15); transition: .15s ease;
    }
    .swatch-btn:hover, .swatch-btn.active { transform: scale(1.18); box-shadow: 0 0 0 3px #e74f83; }
    .chip-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(90px, 1fr)); gap: 6px; }
    .chip-btn {
      padding: 7px 8px; border-radius: 9px; background: #fff0f6; border: 1px solid var(--line);
      font-size: 11px; font-weight: 700; color: var(--ink); text-align: center; cursor: pointer;
      transition: .15s ease;
    }
    .chip-btn:hover { background: #ffe4ee; }
    .chip-btn.active { background: linear-gradient(135deg, #ff6584, #dd2476); color: #fff; border-color: transparent; }
    .user-name { margin: 0; font-weight: 800; display: flex; align-items: center; gap: 6px; }
    .user-meta { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .user-bio-snip {
      font-size: 12px; color: #543846; margin: 8px 0; line-height: 1.45;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    }
    .count { margin: 10px 0; color: var(--muted); font-size: 12px; font-weight: 600; }
    .mini-btn { padding: 7px 11px; border-radius: 8px; color: var(--purple-dark); background: #ffeaf2; font-size: 12px; font-weight: 700; }
    .mini-btn.req { color: #fff; background: linear-gradient(135deg, #ff6584, #dd2476); margin-left: 4px; }
    .mini-btn.delete { color: #cc4c6d; background: #fff1f5; margin-left: 4px; }

    /* Requests */
    .request { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--line); }
    .request:last-child { border-bottom: 0; }
    .request p { margin: 0; font-size: 13px; line-height: 1.4; }
    .request span { color: var(--muted); font-size: 11px; }
    .req-btns { display: flex; gap: 6px; align-items: center; }
    .pill { padding: 5px 9px; border-radius: 20px; color: #b52e60; background: #ffe4ee; font-size: 11px; font-weight: 800; }
    .pill.accept { background: #d1fae5; color: #065f46; cursor: pointer; }
    .pill.reject { background: #fee2e2; color: #991b1b; cursor: pointer; }

    .recent-list, .recommendations { display: grid; gap: 8px; }
    .recent-item, .rec-item { display: flex; justify-content: space-between; padding: 9px 11px; border-radius: 9px; background: #fffcfd; border: 1px solid #f9e6ee; font-size: 13px; }
    .rec-item small { color: var(--muted); }
    .empty { color: var(--muted); padding: 18px 0; text-align: center; font-size: 13px; line-height: 1.6; }

    /* Modals Overlay */
    .modal-backdrop {
      position: fixed; inset: 0; background: rgba(32, 12, 23, .45); backdrop-filter: blur(4px);
      z-index: 100; display: none; place-items: center; padding: 20px;
    }
    .modal-backdrop.open { display: grid; }
    .modal-card {
      background: #ffffff; border-radius: 24px; padding: 32px; width: 100%; max-width: 520px;
      box-shadow: 0 25px 60px rgba(169, 67, 108, .22); position: relative; max-height: 90vh; overflow-y: auto;
    }
    .modal-close {
      position: absolute; right: 20px; top: 20px; width: 34px; height: 34px; border-radius: 50%;
      background: #fff0f5; color: var(--purple-dark); font-size: 16px; font-weight: 800;
      display: grid; place-items: center; cursor: pointer;
    }
    .modal-close:hover { background: #ffe2ee; }

    /* Notification Panel */
    .notif-panel {
      position: absolute; right: 28px; top: 85px; width: 380px; max-width: calc(100vw - 36px);
      background: #fff; border: 1px solid var(--line); border-radius: 20px; padding: 18px 20px;
      box-shadow: 0 18px 45px rgba(169, 67, 108, .18); z-index: 95; display: none;
    }
    .notif-panel.open { display: block; }
    .notif-item { padding: 10px 0; border-bottom: 1px solid var(--line); font-size: 13px; }
    .notif-item:last-child { border-bottom: 0; }
    .notif-item p { margin: 0 0 3px; line-height: 1.4; }
    .notif-tag { font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 6px; }
    .notif-tag.accepted { background: #d1fae5; color: #065f46; }
    .notif-tag.rejected { background: #fee2e2; color: #991b1b; }
    .notif-tag.request { background: #ffe4ee; color: #b52e60; }
    .notif-tag.info { background: #e0f2fe; color: #0369a1; }

    /* Login Portal Card with Breathing Animated Gradient Background */
    .auth-wrapper {
      position: relative;
      min-height: 600px;
      margin: 20px 0 30px;
      border-radius: 28px;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 40px 16px;
      background: #0a0a0a;
      box-shadow: 0 20px 60px rgba(10, 10, 10, 0.45);
    }
    .animated-gradient-bg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 1;
      opacity: 0.95;
      transition: opacity 1s ease;
    }
    .auth-container {
      position: relative;
      z-index: 2;
      max-width: 480px;
      width: 100%;
      margin: 0 auto;
    }
    .auth-card {
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border: 1px solid rgba(255, 255, 255, 0.7);
      border-radius: 24px;
      padding: 36px 32px;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.4), 0 0 35px rgba(255, 93, 143, 0.2);
      text-align: center;
    }
    .auth-logo {
      width: 58px; height: 58px; margin: 0 auto 16px; border-radius: 18px;
      background: linear-gradient(135deg, #ff8eae, #dd3e77); display: grid; place-items: center;
      color: #fff; font-size: 30px; box-shadow: 0 12px 25px rgba(221, 62, 119, .32);
    }
    .auth-header h2 { margin: 0 0 6px; font-size: 24px; letter-spacing: -.6px; }
    .auth-header p { margin: 0; color: var(--muted); font-size: 13px; }
    .auth-tabs { display: flex; background: #fff0f5; padding: 4px; border-radius: 14px; margin-bottom: 24px; }
    .auth-tab {
      flex: 1; padding: 9px 12px; border-radius: 10px; font-weight: 700; font-size: 13px;
      color: var(--muted); background: transparent; transition: .15s;
    }
    .auth-tab.active { background: #ffffff; color: var(--purple-dark); box-shadow: 0 4px 12px rgba(189, 50, 101, .12); }

    /* Interactive Password Strength Box */
    .password-strength-box {
      margin-top: 10px;
      background: #fbfbfe;
      border: 1.5px solid var(--line);
      border-radius: 14px;
      padding: 12px 14px;
      text-align: left;
    }
    .strength-meter-bars {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 6px;
      margin-bottom: 8px;
    }
    .meter-bar {
      position: relative;
      height: 5px;
      background: #e8ebf2;
      border-radius: 3px;
      overflow: hidden;
    }
    .meter-fill {
      position: absolute;
      top: 0; left: 0; bottom: 0; width: 0%;
      border-radius: 3px;
      transition: width 0.3s cubic-bezier(0.25, 0.1, 0.25, 1), background-color 0.25s ease;
    }
    .strength-status-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;
      margin-bottom: 8px;
      min-height: 18px;
    }
    .strength-label {
      font-weight: 700;
      color: #94a3b8;
      transition: color 0.2s ease;
    }
    .strength-warning {
      color: #d97706;
      font-weight: 700;
      font-size: 11px;
    }
    .strength-rules-list {
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 6px;
    }
    .rule-item {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      color: #718096;
      transition: color 0.2s ease;
    }
    .rule-item.met {
      color: #1a202c;
      font-weight: 600;
    }
    .rule-checkbox {
      width: 16px;
      height: 16px;
      border-radius: 4px;
      border: 1.5px solid #cbd5e1;
      display: grid;
      place-items: center;
      background: #fff;
      transition: all 0.2s ease;
      flex: none;
    }
    .rule-checkbox svg {
      width: 10px;
      height: 10px;
      opacity: 0;
      transform: scale(0.6);
      transition: all 0.2s ease;
      color: #fff;
    }
    .rule-item.met .rule-checkbox {
      background: #10b981;
      border-color: #10b981;
    }
    .rule-item.met .rule-checkbox svg {
      opacity: 1;
      transform: scale(1);
    }

    /* Toast */
    .toast {
      position: fixed; right: 24px; bottom: 24px; z-index: 120; max-width: 360px;
      padding: 13px 18px; color: #fff; border-radius: 14px; background: #20283d;
      box-shadow: 0 14px 30px rgba(20, 28, 52, .25); transform: translateY(20px); opacity: 0;
      pointer-events: none; transition: .22s ease; font-size: 13px; font-weight: 600;
    }
    .toast.show { transform: translateY(0); opacity: 1; }
    .toast.error { background: #c5305a; }

    /* STORIES TRAY */
    .stories-tray {
      display: flex;
      gap: 16px;
      overflow-x: auto;
      padding: 8px 4px 16px;
      margin-bottom: 20px;
      scrollbar-width: thin;
      scrollbar-color: rgba(255, 93, 143, 0.3) transparent;
      align-items: center;
    }
    .stories-tray::-webkit-scrollbar { height: 5px; }
    .stories-tray::-webkit-scrollbar-thumb {
      background: rgba(255, 93, 143, 0.3);
      border-radius: 10px;
    }
    .story-item {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      flex-shrink: 0;
      text-align: center;
      transition: transform 0.2s ease;
    }
    .story-item:hover { transform: translateY(-2px); }
    .story-ring {
      width: 66px;
      height: 66px;
      border-radius: 50%;
      padding: 3px;
      background: linear-gradient(135deg, #ff4d88, #ff80ab, #ffd600, #3d5afe);
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
      box-shadow: 0 4px 12px rgba(255, 77, 136, 0.25);
    }
    .story-ring.unseen {
      background: linear-gradient(135deg, #ff007f, #ff758c, #ff7eb3);
      animation: pulseStory 2s infinite ease-in-out;
    }
    .story-ring.empty-mine {
      background: #e2e8f0;
      box-shadow: none;
    }
    @keyframes pulseStory {
      0%, 100% { box-shadow: 0 0 0 0 rgba(255, 77, 136, 0.5); }
      50% { box-shadow: 0 0 0 6px rgba(255, 77, 136, 0); }
    }
    .story-inner {
      width: 100%;
      height: 100%;
      border-radius: 50%;
      background: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      border: 2px solid #fff;
    }
    .story-plus-badge {
      position: absolute;
      bottom: -1px;
      right: -1px;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: #ff4d88;
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 15px;
      font-weight: 800;
      border: 2px solid #fff;
      box-shadow: 0 2px 6px rgba(0,0,0,0.25);
    }
    .story-label {
      font-size: 11px;
      font-weight: 700;
      color: var(--ink);
      max-width: 72px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    /* SECTION NAV TABS */
    .section-nav-tabs {
      display: flex;
      gap: 10px;
      margin-bottom: 22px;
      background: #fff;
      padding: 6px;
      border-radius: 16px;
      box-shadow: var(--shadow);
      border: 1px solid var(--line);
      overflow-x: auto;
    }
    .section-nav-btn {
      flex: 1;
      padding: 11px 18px;
      border: none;
      background: transparent;
      border-radius: 12px;
      font-weight: 700;
      font-size: 14px;
      color: var(--muted);
      cursor: pointer;
      transition: all 0.2s ease;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      white-space: nowrap;
    }
    .section-nav-btn:hover {
      background: #fff0f6;
      color: var(--purple-dark);
    }
    .section-nav-btn.active {
      background: linear-gradient(135deg, #ff4d88, #ff6584);
      color: #fff;
      box-shadow: 0 4px 14px rgba(255, 77, 136, 0.3);
    }

    /* FEED & POSTS */
    .feed-container {
      max-width: 640px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 22px;
    }
    .create-post-card {
      background: #fff;
      border-radius: 20px;
      padding: 20px;
      box-shadow: var(--shadow);
      border: 1px solid var(--line);
    }
    .post-card {
      background: #fff;
      border-radius: 20px;
      overflow: hidden;
      box-shadow: var(--shadow);
      border: 1px solid var(--line);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .post-card:hover {
      box-shadow: 0 14px 34px rgba(60, 20, 40, 0.08);
    }
    .post-header {
      padding: 14px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid #fbf2f6;
    }
    .post-author-box {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .post-author-name {
      font-weight: 800;
      color: var(--ink);
      font-size: 14px;
    }
    .post-time {
      font-size: 11px;
      color: var(--muted);
    }
    .post-img-box {
      width: 100%;
      background: #111;
      max-height: 520px;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }
    .post-img-box img {
      width: 100%;
      height: auto;
      max-height: 520px;
      object-fit: contain;
      display: block;
    }
    .post-actions {
      padding: 12px 18px 8px;
      display: flex;
      align-items: center;
      gap: 14px;
    }
    .like-btn {
      background: none;
      border: none;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 14px;
      font-weight: 700;
      color: var(--ink);
      transition: transform 0.15s ease;
      padding: 6px 12px;
      border-radius: 20px;
    }
    .like-btn:hover { background: #fff0f5; }
    .like-btn.liked { color: #ff1a60; }
    .like-btn.liked .heart-icon { transform: scale(1.2); }
    .post-caption-box {
      padding: 0 18px 16px;
      font-size: 14px;
      line-height: 1.5;
      color: var(--ink);
    }
    .post-caption-box strong {
      color: var(--purple-dark);
      margin-right: 6px;
    }

    /* REAL-TIME CHAT */
    .chat-modal-card {
      width: 100%;
      max-width: 580px;
      height: 82vh;
      max-height: 680px;
      background: #fff;
      border-radius: 24px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 24px 60px rgba(20, 15, 30, 0.35);
      position: relative;
    }
    .chat-header {
      padding: 14px 18px;
      background: linear-gradient(135deg, #fff7fa, #ffe8f1);
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .chat-user-info {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .chat-messages {
      flex: 1;
      padding: 18px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
      background: #faf6f8;
    }
    .chat-bubble {
      max-width: 75%;
      padding: 10px 14px;
      border-radius: 18px;
      font-size: 14px;
      line-height: 1.45;
      position: relative;
      word-wrap: break-word;
      animation: fadeIn 0.18s ease;
    }
    .chat-bubble.mine {
      align-self: flex-end;
      background: linear-gradient(135deg, #ff4d88, #ff6584);
      color: #fff;
      border-bottom-right-radius: 4px;
      box-shadow: 0 4px 14px rgba(255, 77, 136, 0.25);
    }
    .chat-bubble.theirs {
      align-self: flex-start;
      background: #ffffff;
      color: var(--ink);
      border-bottom-left-radius: 4px;
      box-shadow: 0 3px 10px rgba(0,0,0,0.06);
      border: 1px solid #f1e4ec;
    }
    .chat-msg-time {
      display: block;
      font-size: 10px;
      margin-top: 4px;
      opacity: 0.75;
      text-align: right;
    }
    .chat-input-bar {
      padding: 12px 16px;
      background: #fff;
      border-top: 1px solid var(--line);
      display: flex;
      gap: 10px;
      align-items: center;
    }
    .chat-input-bar input {
      flex: 1;
      padding: 12px 16px;
      border-radius: 24px;
      border: 1.5px solid var(--line);
      outline: none;
      font-size: 14px;
      background: #faf6f8;
    }
    .chat-input-bar input:focus {
      border-color: #ff4d88;
      background: #fff;
    }
    .chat-send-btn {
      padding: 10px 20px;
      border-radius: 22px;
      background: linear-gradient(135deg, #ff4d88, #d81b60);
      color: #fff;
      border: none;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s ease;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .chat-send-btn:hover {
      transform: scale(1.03);
      box-shadow: 0 4px 14px rgba(216, 27, 96, 0.35);
    }

    /* STORY VIEWER MODAL */
    .story-viewer-card {
      width: 100%;
      max-width: 440px;
      height: 82vh;
      max-height: 720px;
      background: #000;
      border-radius: 24px;
      position: relative;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 24px 70px rgba(0,0,0,0.6);
      user-select: none;
    }
    .story-progress-bar {
      position: absolute;
      top: 12px;
      left: 12px;
      right: 12px;
      height: 3.5px;
      background: rgba(255,255,255,0.3);
      border-radius: 4px;
      overflow: hidden;
      z-index: 20;
    }
    .story-progress-fill {
      height: 100%;
      background: #fff;
      width: 0%;
      transition: width 0.08s linear;
    }
    .story-top-info {
      position: absolute;
      top: 22px;
      left: 14px;
      right: 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      z-index: 20;
      color: #fff;
      text-shadow: 0 1px 3px rgba(0,0,0,0.6);
    }
    .story-top-user-group {
      display: flex;
      flex-direction: column;
      gap: 3px;
    }
    .story-music-header-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(0,0,0,0.48);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      border: 1px solid rgba(255,255,255,0.22);
      border-radius: 20px;
      padding: 2px 10px;
      font-size: 11px;
      color: #fff;
      max-width: 210px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }
    .story-music-header-pill .song-marquee {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 140px;
      font-weight: 600;
    }
    .story-audio-btn {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: rgba(0,0,0,0.45);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255,255,255,0.25);
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      font-size: 13px;
      transition: all 0.2s;
    }
    .story-audio-btn:hover {
      background: rgba(255,255,255,0.2);
      transform: scale(1.08);
    }
    .story-img-container {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      height: 100%;
      background: #0a0a0a;
      position: relative;
    }
    .story-img-container img,
    .story-img-container video {
      width: 100%;
      height: 100%;
      object-fit: cover;
      pointer-events: none;
    }
    .story-tap-zone-left {
      position: absolute;
      top: 50px;
      bottom: 80px;
      left: 0;
      width: 35%;
      z-index: 15;
      cursor: pointer;
    }
    .story-tap-zone-right {
      position: absolute;
      top: 50px;
      bottom: 80px;
      right: 0;
      width: 65%;
      z-index: 15;
      cursor: pointer;
    }
    .story-caption-overlay {
      position: absolute;
      bottom: 24px;
      left: 14px;
      right: 14px;
      padding: 12px 16px;
      background: rgba(0,0,0,0.65);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid rgba(255,255,255,0.15);
      border-radius: 14px;
      color: #fff;
      font-size: 13px;
      text-align: center;
      z-index: 20;
    }

    /* INSTAGRAM MUSIC STICKERS ON STORY */
    .story-insta-sticker {
      position: absolute;
      z-index: 18;
      cursor: default;
      user-select: none;
      animation: stickerBob 3.5s ease-in-out infinite alternate;
      pointer-events: none;
    }
    @keyframes stickerBob {
      0% { transform: translate(-50%, 0px); }
      100% { transform: translate(-50%, -6px); }
    }
    .sticker-style-card {
      bottom: 85px;
      left: 50%;
      background: rgba(18, 18, 24, 0.78);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.22);
      padding: 8px 14px 8px 8px;
      border-radius: 16px;
      display: flex;
      align-items: center;
      gap: 10px;
      color: #fff;
      box-shadow: 0 10px 28px rgba(0,0,0,0.6);
      max-width: 86%;
    }
    .sticker-style-card .sticker-thumb {
      width: 44px;
      height: 44px;
      border-radius: 10px;
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
      background-size: cover;
      background-position: center;
      box-shadow: 0 3px 8px rgba(0,0,0,0.4);
    }
    .sticker-style-card .sticker-info {
      display: flex;
      flex-direction: column;
      overflow: hidden;
      text-align: left;
    }
    .sticker-style-card .sticker-title {
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .sticker-style-card .sticker-artist {
      font-size: 11px;
      color: #d1d5db;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .sticker-style-pill {
      bottom: 85px;
      left: 50%;
      background: rgba(0, 0, 0, 0.72);
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
      border: 1px solid rgba(255, 255, 255, 0.24);
      padding: 7px 16px;
      border-radius: 30px;
      display: flex;
      align-items: center;
      gap: 8px;
      color: #fff;
      font-size: 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.5);
      max-width: 86%;
      white-space: nowrap;
    }

    .sticker-style-vinyl {
      bottom: 85px;
      left: 50%;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      filter: drop-shadow(0 8px 20px rgba(0,0,0,0.7));
    }
    .insta-vinyl-disc {
      width: 58px;
      height: 58px;
      border-radius: 50%;
      background: repeating-radial-gradient(#111, #111 2px, #242424 3px, #111 4px);
      border: 2px solid #333;
      display: flex;
      align-items: center;
      justify-content: center;
      animation: vinylSpin 6s linear infinite;
    }
    .insta-vinyl-disc.paused {
      animation-play-state: paused;
    }
    .insta-vinyl-center {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background-size: cover;
      background-position: center;
      border: 2px solid #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
    }
    @keyframes vinylSpin {
      0% { transform: rotate(0deg); }
      100% { transform: rotate(360deg); }
    }
    .insta-vinyl-label {
      background: rgba(0,0,0,0.65);
      backdrop-filter: blur(8px);
      padding: 3px 10px;
      border-radius: 12px;
      font-size: 11px;
      color: #fff;
      font-weight: 600;
      white-space: nowrap;
    }

    /* STORY LIKE BUTTON & FLOATING HEARTS */
    .story-heart-btn {
      background: rgba(0,0,0,0.55);
      backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px);
      border: 1px solid rgba(255,255,255,0.25);
      color: #fff;
      border-radius: 50%;
      width: 40px;
      height: 40px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      font-size: 19px;
      flex-shrink: 0;
      position: relative;
      transition: all 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }
    .story-heart-btn:hover {
      background: rgba(255,255,255,0.2);
      transform: scale(1.12);
    }
    .story-heart-btn:active {
      transform: scale(0.9);
    }
    .story-heart-btn.liked {
      background: rgba(255, 77, 136, 0.25);
      border-color: rgba(255, 77, 136, 0.6);
      box-shadow: 0 0 16px rgba(255, 77, 136, 0.45);
    }
    .story-heart-btn.pop-anim {
      animation: heartPop 0.45s cubic-bezier(0.175, 0.885, 0.32, 1.4);
    }
    @keyframes heartPop {
      0% { transform: scale(1); }
      40% { transform: scale(1.45); }
      70% { transform: scale(0.92); }
      100% { transform: scale(1); }
    }
    .story-like-count {
      position: absolute;
      top: -4px;
      right: -4px;
      background: linear-gradient(135deg, #ff4d88, #ff6584);
      color: #fff;
      font-size: 10px;
      font-weight: 700;
      padding: 1px 5px;
      border-radius: 10px;
      box-shadow: 0 2px 6px rgba(0,0,0,0.5);
      line-height: 1.2;
    }

    /* FLOATING HEARTS ANIMATION */
    .story-floating-hearts-container {
      position: absolute;
      inset: 0;
      pointer-events: none;
      overflow: hidden;
      z-index: 30;
    }
    .floating-story-heart {
      position: absolute;
      bottom: 20px;
      right: 20px;
      font-size: 24px;
      user-select: none;
      pointer-events: none;
      animation: floatStoryHeart 1.8s cubic-bezier(0.25, 0.46, 0.45, 0.94) forwards;
    }
    @keyframes floatStoryHeart {
      0% {
        opacity: 1;
        transform: translate3d(0, 0, 0) scale(0.6) rotate(0deg);
      }
      25% {
        opacity: 0.95;
        transform: translate3d(var(--drift-x, -15px), -70px, 0) scale(1.25) rotate(var(--rot, 15deg));
      }
      70% {
        opacity: 0.8;
        transform: translate3d(calc(var(--drift-x, -15px) * 1.5), -200px, 0) scale(1.1) rotate(calc(var(--rot, 15deg) * -1));
      }
      100% {
        opacity: 0;
        transform: translate3d(calc(var(--drift-x, -15px) * 2), -320px, 0) scale(0.85) rotate(calc(var(--rot, 15deg) * 1.5));
      }
    }

    /* STORY OWNER ACTIVITY BAR */
    .story-viewer-activity-row {
      position: absolute;
      bottom: 14px;
      left: 14px;
      right: 14px;
      z-index: 25;
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: rgba(14, 14, 18, 0.75);
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 28px;
      padding: 10px 18px;
      color: #fff;
      cursor: pointer;
      box-shadow: 0 10px 30px rgba(0,0,0,0.5);
      transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .story-viewer-activity-row:hover {
      background: rgba(24, 24, 32, 0.88);
      border-color: rgba(255, 255, 255, 0.35);
      transform: translateY(-2px);
      box-shadow: 0 14px 34px rgba(0,0,0,0.65);
    }
    .story-viewer-activity-row .activity-left {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
    }
    .story-viewer-activity-row .activity-right {
      display: flex;
      align-items: center;
      gap: 5px;
      font-size: 12px;
      font-weight: 600;
      color: #ff6584;
    }
    .story-viewer-activity-row .activity-chevron {
      font-size: 11px;
      transition: transform 0.2s;
    }
    .story-viewer-activity-row:hover .activity-chevron {
      transform: translateY(-2px);
    }

    /* STORY VIEWERS MODAL & ITEMS */
    .viewer-item-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.06);
      transition: all 0.2s ease;
    }
    .viewer-item-row:hover {
      background: rgba(255, 255, 255, 0.08);
      border-color: rgba(255, 255, 255, 0.12);
    }
    .viewer-user-info {
      display: flex;
      align-items: center;
      gap: 12px;
      flex: 1;
      min-width: 0;
    }
    .viewer-names {
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .viewer-names strong {
      font-size: 13px;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .viewer-names small {
      font-size: 11px;
      color: var(--text-muted, #94a3b8);
    }
    .viewer-item-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }
    .viewer-liked-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      background: rgba(255, 77, 136, 0.2);
      border: 1px solid rgba(255, 77, 136, 0.4);
      color: #ff4d88;
      font-size: 11px;
      box-shadow: 0 0 8px rgba(255, 77, 136, 0.3);
    }
    .viewer-chat-btn {
      background: rgba(255, 255, 255, 0.1);
      border: 1px solid rgba(255, 255, 255, 0.15);
      color: #fff;
      border-radius: 20px;
      padding: 5px 12px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: all 0.2s;
    }
    .viewer-chat-btn:hover {
      background: linear-gradient(135deg, #ff4d88, #ff6584);
      border-color: transparent;
      transform: scale(1.04);
    }

    /* INSTAGRAM MUSIC PICKER MODAL */
    .music-picker-card {
      width: 100%;
      max-width: 480px;
      height: 85vh;
      max-height: 640px;
      display: flex;
      flex-direction: column;
      padding: 0;
      border-radius: 24px;
      background: #141419;
      color: #fff;
      overflow: hidden;
      box-shadow: 0 25px 60px rgba(0, 0, 0, 0.7);
      border: 1px solid rgba(255, 255, 255, 0.12);
    }
    .music-picker-header {
      padding: 16px 20px 12px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: #1a1a22;
    }
    .music-search-wrap {
      padding: 12px 16px 8px;
    }
    .music-search-bar {
      display: flex;
      align-items: center;
      background: rgba(255, 255, 255, 0.08);
      border-radius: 14px;
      padding: 8px 14px;
      gap: 10px;
      border: 1px solid rgba(255, 255, 255, 0.1);
      transition: all 0.2s;
    }
    .music-search-bar:focus-within {
      background: rgba(255, 255, 255, 0.12);
      border-color: #ec4899;
      box-shadow: 0 0 0 3px rgba(236, 72, 153, 0.25);
    }
    .music-search-bar input {
      background: transparent;
      border: none;
      outline: none;
      color: #fff;
      font-size: 14px;
      width: 100%;
    }
    .music-search-bar input::placeholder {
      color: #9ca3af;
    }
    .music-categories-tray {
      display: flex;
      gap: 6px;
      padding: 4px 16px 12px;
      overflow-x: auto;
      scrollbar-width: none;
    }
    .music-categories-tray::-webkit-scrollbar {
      display: none;
    }
    .music-cat-pill {
      background: rgba(255, 255, 255, 0.07);
      color: #d1d5db;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 20px;
      padding: 6px 14px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.18s;
    }
    .music-cat-pill:hover,
    .music-cat-pill.active {
      background: linear-gradient(135deg, #ec4899, #be185d);
      color: #fff;
      border-color: transparent;
      transform: translateY(-1px);
    }
    .music-playlist-list {
      flex: 1;
      overflow-y: auto;
      padding: 4px 12px 16px;
    }
    .music-row-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 12px;
      border-radius: 14px;
      cursor: pointer;
      transition: background 0.15s;
      margin-bottom: 3px;
    }
    .music-row-item:hover {
      background: rgba(255, 255, 255, 0.08);
    }
    .music-row-left {
      display: flex;
      align-items: center;
      gap: 12px;
      overflow: hidden;
      flex: 1;
    }
    .music-row-art {
      width: 48px;
      height: 48px;
      border-radius: 10px;
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
      background-size: cover;
      background-position: center;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      position: relative;
    }
    .music-row-details {
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .music-row-title {
      font-size: 14px;
      font-weight: 600;
      color: #fff;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .music-row-artist {
      font-size: 12px;
      color: #9ca3af;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .music-row-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }
    .music-preview-btn {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      border: 1px solid rgba(255, 255, 255, 0.2);
      background: rgba(255, 255, 255, 0.12);
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: all 0.2s;
      font-size: 13px;
    }
    .music-preview-btn:hover {
      background: #ec4899;
      border-color: #ec4899;
      transform: scale(1.08);
    }
    .music-preview-btn.playing {
      background: #ec4899;
      border-color: #ec4899;
    }
    .mini-equalizer-bars {
      display: flex;
      align-items: flex-end;
      gap: 2.5px;
      height: 14px;
    }
    .mini-equalizer-bars span {
      width: 2.5px;
      background: #fff;
      border-radius: 2px;
      animation: eqDance 0.8s ease-in-out infinite alternate;
    }
    .mini-equalizer-bars span:nth-child(1) { height: 35%; animation-delay: 0.1s; }
    .mini-equalizer-bars span:nth-child(2) { height: 95%; animation-delay: 0.35s; }
    .mini-equalizer-bars span:nth-child(3) { height: 60%; animation-delay: 0.2s; }
    .mini-equalizer-bars span:nth-child(4) { height: 100%; animation-delay: 0.45s; }
    @keyframes eqDance {
      0% { height: 25%; }
      100% { height: 100%; }
    }

    /* STORY CREATOR MUSIC ATTACHMENT CARD */
    .attached-music-card {
      background: #fff8fb;
      border: 1.5px solid #f9a8d4;
      border-radius: 14px;
      padding: 10px 14px;
      margin-bottom: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .attached-music-main {
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .attached-music-left {
      display: flex;
      align-items: center;
      gap: 10px;
      overflow: hidden;
    }
    .sticker-selector-row {
      display: flex;
      align-items: center;
      gap: 6px;
      padding-top: 6px;
      border-top: 1px dashed #fbcfe8;
    }
    .sticker-opt-pill {
      background: #fff;
      border: 1px solid #f472b6;
      color: #be185d;
      border-radius: 16px;
      padding: 4px 10px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s;
    }
    .sticker-opt-pill.active {
      background: #be185d;
      color: #fff;
    }

    /* PRIVACY LOCK BANNER & BADGES */
    .private-lock-box {
      background: #fff;
      border: 1.5px dashed #f472b6;
      border-radius: 18px;
      padding: 28px 20px;
      text-align: center;
      margin: 16px 0;
    }
    .privacy-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 11px;
      font-weight: 800;
      padding: 3px 8px;
      border-radius: 10px;
    }
    .privacy-badge.public {
      background: #e0f2fe;
      color: #0369a1;
    }
    .privacy-badge.private {
      background: #fce7f3;
      color: #be185d;
    }


    @media (max-width: 950px) { .layout { grid-template-columns: 1fr; } .stats { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); } }
    @media (max-width: 620px) {
      .shell { padding: 18px 14px 36px; }
      .topbar { align-items: flex-start; flex-direction: column; margin-bottom: 18px; }
      .hero { padding: 24px 20px; }
      .hero h2 { font-size: 24px; }
      .user-grid { grid-template-columns: 1fr; }
      .card-head { align-items: stretch; flex-direction: column; }
      .search { width: 100%; }
      .stats { gap: 10px; }
      .stat { padding: 14px; }
      .notif-panel { right: 14px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="logo">♥</div>
        <div>
          <h1>LoveLoop</h1>
          <p>Real-time Connections & Social Network</p>
        </div>
      </div>
      <div class="top-actions">
        <div class="live-pill"><span class="live-dot"></span> Real-time Live Sync</div>
        <button class="notif-btn" id="notifBtn" style="display:none">
          🔔 Notifications <span class="notif-count" id="notifBadge">0</span>
        </button>
        <button class="notif-btn" id="topbarChatBtn" style="display:none;background:#fff0f6;border-color:#f9c2d8;color:#be185d">
          💬 Direct Messages
        </button>
        <div id="authPillContainer"></div>
        <button class="btn btn-soft" id="myProfileBtn" style="display:none">👤 My Profile</button>
        <button class="btn btn-soft" id="undoBtn" style="display:none">↶ Undo</button>
        <button class="btn btn-danger" id="logoutBtn" style="display:none">Log out</button>
      </div>
    </header>

    <!-- NOTIFICATION DROPDOWN PANEL -->
    <div class="notif-panel" id="notifPanel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <strong style="color:var(--purple-dark);font-size:15px">Notifications 💕</strong>
        <button class="mini-btn" id="clearNotifsBtn" style="padding:4px 8px;font-size:11px">Clear all</button>
      </div>
      <div id="notifList" style="max-height:280px;overflow-y:auto"></div>
    </div>

    <!-- AUTHENTICATION VIEW (When not logged in) -->
    <div id="authView" class="auth-wrapper">
      <div class="animated-gradient-bg" id="authGradientBg"></div>
      <div class="auth-container">
        <div class="auth-card">
          <div class="auth-logo">♥</div>
          <div class="auth-header">
            <h2>Welcome to LoveLoop 💕</h2>
            <p>Log in with your username & password to access real-time connections.</p>
          </div>

          <div class="auth-tabs">
            <button class="auth-tab active" data-tab="user-login">💕 User Login</button>
            <button class="auth-tab" data-tab="admin-login">👑 Admin Portal</button>
            <button class="auth-tab" data-tab="register">✨ Sign Up</button>
          </div>

          <!-- Tab 1: Normal User Login -->
          <form id="userLoginForm">
            <div class="field" style="text-align:left">
              <label>Username</label>
              <input name="username" id="userLoginName" placeholder="Enter your username" required autocomplete="username">
            </div>
            <div class="field" style="text-align:left">
              <label>Password</label>
              <input name="password" id="userLoginPass" type="password" placeholder="Enter your password" required autocomplete="current-password">
            </div>
            <button class="btn btn-primary" style="width:100%;margin-top:10px" type="submit">💖 Log In as User</button>
          </form>

          <!-- Tab 2: Admin Login -->
          <form id="adminLoginForm" style="display:none">
            <div class="field" style="text-align:left">
              <label>Administrator Username</label>
              <input name="username" id="adminLoginName" placeholder="Enter admin username" required autocomplete="username">
            </div>
            <div class="field" style="text-align:left">
              <label>Admin Password</label>
              <input name="password" id="adminLoginPass" type="password" placeholder="Enter admin password" required autocomplete="current-password">
            </div>
            <button class="btn btn-primary" style="width:100%;margin-top:10px;background:linear-gradient(135deg,#f59e0b,#d97706)" type="submit">👑 Enter Admin Console</button>
          </form>

          <!-- Tab 3: Create Account -->
          <form id="registerForm" style="display:none">
            <div class="field" style="text-align:left">
              <label>Choose Username</label>
              <input name="username" placeholder="Choose a username" required minlength="2">
            </div>
            <div class="field" style="text-align:left">
              <label>Create Password</label>
              <input name="password" id="regPasswordInput" type="password" placeholder="Choose a secure password" required minlength="3" autocomplete="new-password">

              <!-- Interactive Password Strength Meter -->
              <div id="passwordStrengthBox" class="password-strength-box">
                <div class="strength-meter-bars" role="meter" aria-label="Password strength" aria-valuemin="0" aria-valuemax="4">
                  <div class="meter-bar"><span class="meter-fill" id="meterFill0"></span></div>
                  <div class="meter-bar"><span class="meter-fill" id="meterFill1"></span></div>
                  <div class="meter-bar"><span class="meter-fill" id="meterFill2"></span></div>
                  <div class="meter-bar"><span class="meter-fill" id="meterFill3"></span></div>
                </div>

                <div class="strength-status-row">
                  <span class="strength-label" id="strengthLabel">Empty</span>
                  <span class="strength-warning" id="strengthWarning" style="display:none">⚠️ Commonly guessed pattern</span>
                </div>

                <ul class="strength-rules-list">
                  <li class="rule-item" id="ruleLength">
                    <span class="rule-checkbox"><svg viewBox="0 0 12 12"><path d="M2 6.2 4.7 8.9 10 3.3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg></span>
                    <span class="rule-text">12 characters or more</span>
                  </li>
                  <li class="rule-item" id="ruleCase">
                    <span class="rule-checkbox"><svg viewBox="0 0 12 12"><path d="M2 6.2 4.7 8.9 10 3.3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg></span>
                    <span class="rule-text">Upper and lower case</span>
                  </li>
                  <li class="rule-item" id="ruleDigit">
                    <span class="rule-checkbox"><svg viewBox="0 0 12 12"><path d="M2 6.2 4.7 8.9 10 3.3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg></span>
                    <span class="rule-text">A number</span>
                  </li>
                  <li class="rule-item" id="ruleSymbol">
                    <span class="rule-checkbox"><svg viewBox="0 0 12 12"><path d="M2 6.2 4.7 8.9 10 3.3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg></span>
                    <span class="rule-text">A symbol</span>
                  </li>
                </ul>
              </div>
            </div>
            <div class="form-row">
              <div class="field" style="text-align:left">
                <label>Age (Optional)</label>
                <input name="age" type="number" min="1" placeholder="Age">
              </div>
              <div class="field" style="text-align:left">
                <label>City (Optional)</label>
                <input name="city" placeholder="City">
              </div>
            </div>
            <div class="field" style="text-align:left">
              <label>Short Bio (Optional)</label>
              <input name="bio" placeholder="Write something sweet about yourself...">
            </div>
            <button class="btn btn-primary" style="width:100%;margin-top:10px" type="submit">✨ Create My Account & Join</button>
          </form>
        </div>
      </div>
    </div>

    <!-- MAIN APP DASHBOARD (When authenticated) -->
    <div id="mainDashboard" style="display:none">
      <section class="hero">
        <div class="eyebrow" style="color:#ffd3e1" id="heroEyebrow">YOUR LOVE NETWORK AT A GLANCE</div>
        <h2 id="heroTitle">Make room for the connections that feel right.</h2>
        <p id="heroSubtitle">Discover your people, nurture new sparks, and keep every meaningful connection close.</p>
      </section>

      <!-- STORIES TRAY (24-Hour Expiring Stories) -->
      <div style="background:#fff;border-radius:20px;padding:14px 18px 6px;margin-bottom:20px;box-shadow:var(--shadow);border:1px solid var(--line)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <strong style="font-size:13px;color:var(--purple-dark);display:flex;align-items:center;gap:6px">✨ Stories <span style="font-size:11px;color:var(--muted);font-weight:600">24h moments</span></strong>
          <button class="mini-btn" id="openAddStoryBtn" type="button" style="background:#fff0f6;border:1px solid #f9c2d8;color:#be185d;font-size:11px">➕ Add Story</button>
        </div>
        <div class="stories-tray" id="storiesTray">
          <div class="story-item" id="addStoryCircle">
            <div class="story-ring empty-mine" id="myStoryRing">
              <div class="story-inner" id="myStoryAvatarSlot"></div>
              <div class="story-plus-badge">＋</div>
            </div>
            <span class="story-label">Your story</span>
          </div>
          <div id="storiesListContainer" style="display:flex;gap:16px"></div>
        </div>
      </div>

      <!-- MAIN NAVIGATION TABS -->
      <nav class="section-nav-tabs">
        <button class="section-nav-btn active" id="tabBtnConnections" type="button">👥 Connections & Friends</button>
        <button class="section-nav-btn" id="tabBtnFeed" type="button">📸 LoveFeed (<span id="feedCountBadge">0</span>)</button>
        <button class="section-nav-btn" id="tabBtnChats" type="button">💬 Direct Messages</button>
      </nav>

      <!-- TAB 1: CONNECTIONS VIEW -->
      <div id="connectionsView">
        <section class="stats">
          <div class="stat"><small id="statUsersLabel">Friends</small><strong id="statUsers">0</strong></div>
          <div class="stat"><small>Friendships</small><strong id="statFriends">0</strong></div>
          <div class="stat"><small id="statPendingLabel">Pending requests</small><strong id="statPending">0</strong></div>
        </section>

        <div class="layout">
          <!-- Left: People Grid -->
          <section class="card">
            <!-- User View Filter Tabs: Only Friends vs Discover (Admin sees all) -->
            <div id="userTabsContainer" class="tab-pills" style="display:none">
              <button class="tab-pill active" id="tabMyFriends">💕 My Friends (<span id="myFriendsCount">0</span>)</button>
              <button class="tab-pill" id="tabDiscover">🔍 Discover New People (<span id="discoverCount">0</span>)</button>
            </div>

            <div class="card-head">
              <div>
                <div class="eyebrow" id="gridEyebrow">Your Circle</div>
                <h3 id="gridTitle">My Friends</h3>
              </div>
              <input class="search" id="searchInput" placeholder="Search profiles..." autocomplete="off">
            </div>
            <div class="user-grid" id="userGrid"></div>
          </section>

          <!-- Right: Actions & Requests -->
          <aside class="stack">
            <!-- ADMIN ONLY: Add Profile -->
            <section class="card" id="adminAddSection" style="display:none">
              <div class="card-head">
                <div>
                  <div class="eyebrow">Admin Console</div>
                  <h3>Add a profile</h3>
                </div>
              </div>
              <form id="adminUserForm">
                <div class="field"><label>Profile name</label><input name="username" placeholder="e.g. alex" required></div>
                <div class="form-row">
                  <div class="field"><label>Age</label><input name="age" type="number" min="1" placeholder="Optional"></div>
                  <div class="field"><label>City</label><input name="city" placeholder="Optional"></div>
                </div>
                <div class="field"><label>Bio</label><input name="bio" placeholder="Profile bio"></div>
                <div class="form-row">
                  <div class="field"><label>Initial Password</label><input name="password" placeholder="Set password"></div>
                  <div class="field"><label>Role</label><select name="role"><option value="user">User</option><option value="admin">Admin</option></select></div>
                </div>
                <button class="btn btn-primary" type="submit">♡ Add profile</button>
              </form>
            </section>

            <!-- SEND CONNECTION REQUEST -->
            <section class="card" id="connectionSection">
              <div class="card-head">
                <div>
                  <div class="eyebrow">Connections</div>
                  <h3 id="connectCardTitle">Send Connection Request</h3>
                </div>
              </div>
              <form id="friendForm">
                <div class="form-row" id="adminConnectRow" style="display:none">
                  <div class="field"><label>First person</label><select name="user_a" id="user_a" class="user-select"></select></div>
                  <div class="field"><label>Second person</label><select name="user_b" id="user_b_admin" class="user-select"></select></div>
                </div>
                <div class="field" id="userConnectField">
                  <label>Send Request to:</label>
                  <select name="user_b" id="user_b" class="user-select"></select>
                </div>
                <div class="form-actions" style="flex-wrap:wrap;gap:8px;">
                  <button class="btn btn-primary" id="sendRequestBtn" type="button" style="background:linear-gradient(135deg,#ff5d8f,#d81b60)">💌 Send Request</button>
                  <button class="btn btn-soft" id="directConnectBtn" type="submit" style="display:none">♡ Direct Connect</button>
                  <button class="btn btn-danger" id="removeFriendBtn" type="button" style="display:none">Remove Friendship</button>
                </div>
              </form>
            </section>

            <!-- LOVE NOTES & REQUESTS (With Accept and Reject) -->
            <section class="card">
              <div class="card-head">
                <div>
                  <div class="eyebrow">Love notes</div>
                  <h3>Connection requests <span class="pill" id="requestBadge">0</span></h3>
                </div>
                <button class="btn btn-soft" id="processBtn" type="button" style="display:none">Accept next in queue</button>
              </div>
              <div id="requestList"></div>
            </section>

            <!-- RECOMMENDATIONS -->
            <section class="card">
              <div class="card-head">
                <div>
                  <div class="eyebrow">Discover</div>
                  <h3>Possible matches</h3>
                </div>
                <select id="recommendSelect" style="width:150px;display:none"></select>
              </div>
              <div class="recommendations" id="recommendations">
                <div class="empty">Loading recommendations...</div>
              </div>
            </section>

            <!-- RECENTLY VIEWED -->
            <section class="card">
              <div class="card-head">
                <div>
                  <div class="eyebrow">Your trail</div>
                  <h3>Recently viewed</h3>
                </div>
              </div>
              <div class="recent-list" id="recentList"></div>
            </section>
          </aside>
        </div>
      </div>

      <!-- TAB 2: LOVEFEED POSTS VIEW -->
      <div id="feedView" style="display:none">
        <div class="feed-container">
          <!-- CREATE POST CARD -->
          <div class="create-post-card">
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
              <div id="createPostAvatar"></div>
              <div>
                <strong style="color:var(--purple-dark);font-size:15px">Create a New Post 📸</strong>
                <p style="margin:2px 0 0;font-size:12px;color:var(--muted)">Share photos with your friends and community</p>
              </div>
            </div>

            <input type="file" id="postFileInput" accept="image/*" style="display:none">
            <div id="postImageUploadBox" style="border:2px dashed #f472b6;background:#fff8fb;border-radius:16px;padding:24px;text-align:center;cursor:pointer;margin-bottom:14px;transition:background .2s ease">
              <div id="postUploadPrompt">
                <span style="font-size:36px">📷</span>
                <p style="margin:6px 0 2px;font-weight:700;color:var(--purple-dark)">Click to select a photo from your device</p>
                <small style="color:var(--muted)">JPG or PNG image</small>
              </div>
              <img id="postSelectedPreview" style="display:none;max-height:360px;width:auto;margin:0 auto;border-radius:12px;box-shadow:0 4px 14px rgba(0,0,0,0.1)">
            </div>

            <div class="field" style="margin-bottom:12px;text-align:left">
              <label>Caption</label>
              <textarea id="postCaptionInput" rows="2" placeholder="Write a lovely caption for this moment..." maxlength="300"></textarea>
            </div>

            <div style="display:flex;justify-content:flex-end;gap:10px">
              <button class="btn btn-soft" id="cancelPostImgBtn" type="button" style="display:none">Clear Image</button>
              <button class="btn btn-primary" id="publishPostBtn" type="button">✨ Post to LoveFeed</button>
            </div>
          </div>

          <!-- POSTS FEED LIST -->
          <div id="feedPostsContainer" style="display:flex;flex-direction:column;gap:20px">
            <div class="empty">Loading LoveFeed...</div>
          </div>
        </div>
      </div>

      <!-- TAB 3: DIRECT MESSAGES VIEW -->
      <div id="chatsView" style="display:none">
        <div style="max-width:680px;margin:0 auto">
          <div class="card">
            <div class="card-head">
              <div>
                <div class="eyebrow">Real-Time Messaging</div>
                <h3>Direct Messages & Chats 💬</h3>
              </div>
            </div>
            <div style="margin-bottom:14px">
              <input id="chatUserSearchInput" placeholder="🔍 Search friend or user to chat..." style="width:100%;padding:10px 16px;border-radius:20px;border:1.5px solid var(--line);outline:none;font-size:13px;background:#faf6f8">
            </div>
            <div id="chatFriendsList" style="display:flex;flex-direction:column;gap:10px">
              <div class="empty">Loading friend chats...</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </main>

  <!-- VIEW PROFILE DETAILS MODAL (Fix for View option) -->
  <div class="modal-backdrop" id="viewProfileModal">
    <div class="modal-card">
      <div class="modal-close" id="closeViewModal">✕</div>
      <div style="text-align:center;margin-bottom:16px">
        <div class="avatar" id="viewAvatar" style="width:68px;height:68px;font-size:24px;margin:0 auto 10px">?</div>
        <h2 id="viewUsername" style="margin:0 0 2px;font-size:22px">Profile</h2>
        <div id="viewPrivacyBadgeContainer" style="margin-bottom:4px"></div>
        <div id="viewMeta" style="color:var(--muted);font-size:13px">Location · Age</div>
      </div>

      <!-- PRIVATE ACCOUNT LOCK BANNER -->
      <div id="viewPrivateLockBanner" class="private-lock-box" style="display:none">
        <span style="font-size:36px">🔒</span>
        <h3 style="margin:10px 0 4px;font-size:17px;color:var(--purple-dark)">This Account is Private</h3>
        <p style="margin:0 0 14px;font-size:13px;color:var(--muted);line-height:1.4">Connect with this user to view their bio, stories, and LoveFeed photos.</p>
      </div>

      <!-- PROFILE CONTENT (Hidden if private and not friend/admin) -->
      <div id="viewProfileContentSection">
        <div style="background:#fff7fb;border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:18px">
          <small style="color:var(--purple);font-weight:800;text-transform:uppercase;font-size:10px;display:block;margin-bottom:6px">Bio / About</small>
          <p id="viewBio" style="margin:0;font-size:14px;line-height:1.5;color:var(--ink);font-style:italic">"No bio added yet."</p>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px">
          <div style="background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px;text-align:center">
            <small style="color:var(--muted);font-size:11px;font-weight:700">CONNECTIONS</small>
            <strong id="viewFriendsCount" style="display:block;font-size:20px;margin-top:4px">0</strong>
          </div>
          <div style="background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px;text-align:center">
            <small style="color:var(--muted);font-size:11px;font-weight:700">MUTUAL FRIENDS</small>
            <strong id="viewMutualCount" style="display:block;font-size:20px;margin-top:4px">0</strong>
          </div>
        </div>
        <div id="viewMutualList" style="margin-bottom:18px;font-size:12px;color:var(--muted)"></div>
        <div id="viewUserPostsContainer" style="margin-bottom:16px;max-height:200px;overflow-y:auto;display:none">
          <small style="color:var(--muted);font-weight:700;display:block;margin-bottom:8px">USER POSTS</small>
          <div id="viewUserPostsList" style="display:grid;grid-template-columns:repeat(auto-fill, minmax(70px, 1fr));gap:6px"></div>
        </div>
      </div>

      <div id="viewActionContainer" style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap"></div>
    </div>
  </div>

  <!-- MY PROFILE & EDIT BIO MODAL -->
  <div class="modal-backdrop" id="myProfileModal">
    <div class="modal-card">
      <div class="modal-close" id="closeMyProfileModal">✕</div>
      <div style="text-align:center;margin-bottom:18px">
        <div class="avatar" id="myAvatar" style="width:78px;height:78px;margin:0 auto 10px;cursor:pointer" title="Your Profile Photo"></div>
        
        <input type="file" id="profilePhotoFileInput" accept="image/*" style="display:none">
        <div style="display:flex;gap:6px;justify-content:center;margin:6px 0 10px;flex-wrap:wrap">
          <button class="btn btn-primary" type="button" id="uploadPhotoBtn" style="font-size:12px;padding:6px 14px">📷 Upload Photo</button>
          <button class="btn btn-soft" id="openAvatarStudioBtn" type="button" style="font-size:12px;padding:6px 14px">✨ Avatar Studio</button>
          <button class="mini-btn delete" type="button" id="removePhotoBtn" style="font-size:11px;display:none">Remove Photo</button>
        </div>

        <h2 id="myUsername" style="margin:4px 0 2px;font-size:22px">My Profile</h2>
        <span class="user-pill" id="myRoleBadge" style="margin-top:4px">User</span>
      </div>

      <!-- Profile View Mode -->
      <div id="myProfileViewMode">
        <div style="margin-bottom:14px;background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px 14px;display:flex;align-items:center;justify-content:space-between">
          <div>
            <strong style="font-size:11px;color:var(--muted);display:block;margin-bottom:2px">ACCOUNT PRIVACY</strong>
            <span id="myPrivacyDisplay" class="privacy-badge public">🌐 Public Account</span>
          </div>
          <button class="mini-btn" id="togglePrivacyBtn" type="button" style="background:#fff0f6;border:1px solid #f9c2d8">Toggle Privacy</button>
        </div>

        <div style="background:#fff7fb;border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:18px">
          <small style="color:var(--purple);font-weight:800;text-transform:uppercase;font-size:10px;display:block;margin-bottom:6px">My Bio</small>
          <p id="myBioDisplay" style="margin:0;font-size:14px;line-height:1.5;font-style:italic">"No bio added yet. Add one below!"</p>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px;font-size:13px">
          <div style="background:#fff;border:1px solid var(--line);padding:10px;border-radius:10px">
            <strong style="color:var(--muted);display:block;font-size:11px">AGE</strong>
            <span id="myAgeDisplay">Not set</span>
          </div>
          <div style="background:#fff;border:1px solid var(--line);padding:10px;border-radius:10px">
            <strong style="color:var(--muted);display:block;font-size:11px">CITY</strong>
            <span id="myCityDisplay">Not set</span>
          </div>
        </div>
        <button class="btn btn-primary" id="startEditProfileBtn" style="width:100%">✏️ Edit Personal Info & Bio</button>
      </div>

      <!-- Profile Edit Mode -->
      <form id="editProfileForm" style="display:none">
        <div class="field" style="text-align:left">
          <label>Bio (Tell people about yourself)</label>
          <textarea name="bio" id="editBioInput" rows="3" placeholder="Write something sweet about yourself..."></textarea>
        </div>
        <div class="field" style="text-align:left">
          <label>Account Privacy</label>
          <select name="privacy" id="editPrivacySelect">
            <option value="public">🌐 Public (Anyone can view profile, posts & stories)</option>
            <option value="private">🔒 Private (Only confirmed friends can view)</option>
          </select>
        </div>
        <div class="form-row">
          <div class="field" style="text-align:left">
            <label>Age</label>
            <input name="age" id="editAgeInput" type="number" min="1" placeholder="Age">
          </div>
          <div class="field" style="text-align:left">
            <label>City</label>
            <input name="city" id="editCityInput" placeholder="City">
          </div>
        </div>
        <div style="display:flex;gap:8px;margin-top:12px">
          <button class="btn btn-primary" type="submit" style="flex:1">💾 Save Changes</button>
          <button class="btn btn-soft" type="button" id="cancelEditProfileBtn">Cancel</button>
        </div>
      </form>
    </div>
  </div>

  <!-- REAL-TIME CHAT MODAL -->
  <div class="modal-backdrop" id="liveChatModal" style="z-index:9999">
    <div class="chat-modal-card">
      <div class="chat-header">
        <div class="chat-user-info">
          <div id="chatPartnerAvatar"></div>
          <div>
            <h4 id="chatPartnerName" style="margin:0;font-size:15px;color:var(--purple-dark)">Chat</h4>
            <small style="color:#059669;font-weight:700;display:flex;align-items:center;gap:4px">
              <span style="width:7px;height:7px;border-radius:50%;background:#059669;display:inline-block"></span> Live Real-Time Chat
            </small>
          </div>
        </div>
        <div class="modal-close" id="closeChatModal" style="position:static">✕</div>
      </div>
      <div class="chat-messages" id="chatMessageList">
        <div class="empty">Start a conversation 💕</div>
      </div>
      <form class="chat-input-bar" id="chatForm">
        <input type="text" id="chatMessageInput" placeholder="Type a message... (Press Enter to send)" autocomplete="off" required maxlength="500">
        <button class="chat-send-btn" type="submit">💬 Send</button>
      </form>
    </div>
  </div>

  <!-- CREATE STORY MODAL -->
  <div class="modal-backdrop" id="createStoryModal">
    <div class="modal-card" style="max-width:440px">
      <div class="modal-close" id="closeCreateStoryModal">✕</div>
      <h3 style="margin:0 0 6px;font-size:18px">Add to Story ✨</h3>
      <p style="margin:0 0 12px;color:var(--muted);font-size:13px">Share photos, videos & trending music with friends. Stories expire after 24 hours.</p>
      
      <input type="file" id="storyFileInput" accept="image/*,video/*" style="display:none">
      <div id="storyImagePreviewBox" style="width:100%;height:220px;background:#fff8fb;border:2px dashed #f472b6;border-radius:16px;display:flex;align-items:center;justify-content:center;cursor:pointer;overflow:hidden;margin-bottom:12px;position:relative">
        <div id="storyUploadPrompt" style="text-align:center;color:var(--muted)">
          <span style="font-size:36px">📸 🎬</span>
          <p style="margin:6px 0 2px;font-weight:700;font-size:13px;color:var(--purple-dark)">Tap to choose Photo or Video</p>
          <small style="color:var(--muted);font-size:11px">Supports JPG, PNG, MP4, MOV, WebM</small>
        </div>
        <img id="storyPreviewImg" style="display:none;width:100%;height:100%;object-fit:cover">
        <video id="storyPreviewVideo" playsinline autoplay muted loop style="display:none;width:100%;height:100%;object-fit:cover"></video>
        <div id="storyMediaTypeBadge" style="display:none;position:absolute;top:10px;right:10px;background:rgba(0,0,0,0.65);color:#fff;border-radius:12px;padding:3px 8px;font-size:11px;font-weight:600"></div>
      </div>

      <!-- Add Music Trigger -->
      <div id="storyMusicTriggerWrap" style="margin-bottom:12px">
        <button type="button" class="btn" id="openMusicPickerBtn" style="width:100%;background:linear-gradient(135deg, #ec4899, #8b5cf6);color:#fff;border:none;display:flex;align-items:center;justify-content:center;gap:8px;font-weight:700;box-shadow:0 4px 14px rgba(236,72,153,0.3)">
          <span style="font-size:16px">🎵</span> Add Music / Song (Instagram Style)
        </button>
      </div>

      <!-- Attached Music Details (Hidden by default) -->
      <div id="attachedMusicCard" class="attached-music-card" style="display:none">
        <div class="attached-music-main">
          <div class="attached-music-left">
            <div id="attachedSongArt" style="width:38px;height:38px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px;background:linear-gradient(135deg,#ec4899,#8b5cf6);color:#fff;box-shadow:0 2px 6px rgba(0,0,0,0.2)">🎵</div>
            <div style="overflow:hidden;text-align:left">
              <strong id="attachedSongTitle" style="font-size:13px;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--purple-dark)">Song Title</strong>
              <small id="attachedSongArtist" style="font-size:11px;color:var(--muted);display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">Artist</small>
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:6px">
            <button type="button" class="mini-btn" id="attachedPreviewBtn" title="Preview" style="background:#fff;border:1px solid #f472b6">▶</button>
            <button type="button" class="mini-btn" id="attachedChangeBtn" style="background:#fff;border:1px solid #f472b6">Change</button>
            <button type="button" class="mini-btn delete" id="attachedRemoveBtn" title="Remove">✕</button>
          </div>
        </div>
        <div class="sticker-selector-row">
          <span style="font-size:11px;color:var(--muted);font-weight:700">Sticker:</span>
          <button type="button" class="sticker-opt-pill active" data-sticker="card">🎴 Card</button>
          <button type="button" class="sticker-opt-pill" data-sticker="pill">💊 Pill</button>
          <button type="button" class="sticker-opt-pill" data-sticker="vinyl">💿 Vinyl</button>
        </div>
      </div>

      <div class="field" style="text-align:left">
        <label>Story Caption (Optional)</label>
        <input id="storyCaptionInput" placeholder="Add a sweet note or vibes..." maxlength="120">
      </div>
      <div style="display:flex;gap:8px;margin-top:10px">
        <button class="btn btn-primary" id="publishStoryBtn" style="flex:1" type="button">✨ Share to Story</button>
        <button class="btn btn-soft" id="cancelStoryBtn" type="button">Cancel</button>
      </div>
    </div>
  </div>

  <!-- INSTAGRAM MUSIC PICKER MODAL -->
  <div class="modal-backdrop" id="musicPickerModal" style="background:rgba(0,0,0,0.86);z-index:9999">
    <div class="music-picker-card">
      <div class="music-picker-header">
        <div style="display:flex;align-items:center;gap:8px">
          <span style="font-size:18px">🎵</span>
          <strong style="font-size:16px;letter-spacing:-0.2px">Music Playlist</strong>
        </div>
        <div class="modal-close" id="closeMusicPickerModal" style="position:static;color:#fff;background:rgba(255,255,255,0.15)">✕</div>
      </div>

      <div class="music-search-wrap">
        <div class="music-search-bar">
          <span>🔍</span>
          <input type="text" id="musicSearchInput" placeholder="Search songs, artists, hits...">
          <span id="musicSearchClear" style="cursor:pointer;display:none;color:#9ca3af;font-size:12px">✕</span>
        </div>
      </div>

      <div class="music-categories-tray" id="musicCatTray">
        <button type="button" class="music-cat-pill active" data-cat="trending">🔥 For You</button>
        <button type="button" class="music-cat-pill" data-cat="love">💖 Romance</button>
        <button type="button" class="music-cat-pill" data-cat="bollywood">🇮🇳 Bollywood</button>
        <button type="button" class="music-cat-pill" data-cat="pop">🎧 Pop & Beats</button>
        <button type="button" class="music-cat-pill" data-cat="lofi">🌙 Lo-Fi Chill</button>
        <button type="button" class="music-cat-pill" data-cat="custom">📁 Custom / Upload</button>
      </div>

      <!-- Playlist items list -->
      <div class="music-playlist-list" id="musicPlaylistList">
        <!-- Populated dynamically via JS -->
      </div>

      <!-- Custom Upload / URL panel -->
      <div id="customMusicUploadPanel" style="display:none;padding:16px;background:rgba(255,255,255,0.03);border-top:1px solid rgba(255,255,255,0.08);flex:1;overflow-y:auto">
        <h4 style="margin:0 0 6px;font-size:14px;color:#fff">📁 Add Your Own Song</h4>
        <p style="margin:0 0 12px;font-size:12px;color:#9ca3af">Upload an MP3/audio file from your phone/PC or paste an audio URL.</p>
        <input type="file" id="customAudioFileInput" accept="audio/*" style="display:none">
        <button type="button" id="triggerAudioFileBtn" class="btn" style="width:100%;background:rgba(255,255,255,0.08);color:#fff;border:1px dashed #ec4899;margin-bottom:12px">
          🎵 Choose Audio File (.mp3, .wav, .m4a)
        </button>
        <div class="field" style="margin-bottom:8px">
          <label style="color:#d1d5db;font-size:11px">OR Direct Audio URL</label>
          <input id="customAudioUrlInput" placeholder="https://example.com/audio.mp3" style="background:rgba(255,255,255,0.08);color:#fff;border-color:rgba(255,255,255,0.15)">
        </div>
        <div class="field" style="margin-bottom:8px">
          <label style="color:#d1d5db;font-size:11px">Song Title</label>
          <input id="customSongTitleInput" placeholder="E.g. My Favorite Melody" style="background:rgba(255,255,255,0.08);color:#fff;border-color:rgba(255,255,255,0.15)">
        </div>
        <div class="field" style="margin-bottom:12px">
          <label style="color:#d1d5db;font-size:11px">Artist</label>
          <input id="customSongArtistInput" placeholder="E.g. Independent Artist" style="background:rgba(255,255,255,0.08);color:#fff;border-color:rgba(255,255,255,0.15)">
        </div>
        <button type="button" class="btn btn-primary" id="useCustomSongBtn" style="width:100%">✨ Apply Custom Song</button>
      </div>
    </div>
  </div>

  <!-- STORY VIEWER MODAL -->
  <div class="modal-backdrop" id="storyViewerModal" style="background:rgba(0,0,0,0.92);z-index:9999">
    <div class="story-viewer-card" id="storyViewerCard">
      <div class="story-progress-bar">
        <div class="story-progress-fill" id="storyProgressFill"></div>
      </div>
      <div class="story-top-info">
        <div style="display:flex;align-items:center;gap:10px">
          <div id="storyViewerAvatar" style="width:36px;height:36px;border-radius:50%;overflow:hidden;flex-shrink:0"></div>
          <div class="story-top-user-group">
            <div style="display:flex;align-items:center;gap:6px">
              <strong id="storyViewerUsername" style="font-size:13px">Username</strong>
              <small id="storyViewerTime" style="font-size:10px;opacity:0.8">Just now</small>
            </div>
            <!-- Instagram Music Header Pill -->
            <div id="storyViewerMusicBadge" class="story-music-header-pill" style="display:none">
              <span>🎵</span>
              <span class="song-marquee" id="storyViewerMusicText">Song Title • Artist</span>
              <div class="mini-equalizer-bars" id="headerEqualizerBars">
                <span></span><span></span><span></span><span></span>
              </div>
            </div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <button class="story-audio-btn" id="storyAudioToggleBtn" title="Toggle Sound">🔊</button>
          <button class="mini-btn delete" id="deleteCurrentStoryBtn" style="display:none;background:rgba(239,68,68,0.85);color:#fff;border:none">Delete</button>
          <div class="modal-close" id="closeStoryViewerModal" style="position:static;color:#fff;background:rgba(255,255,255,0.25)">✕</div>
        </div>
      </div>

      <!-- Tap zones for Instagram style previous / next navigation -->
      <div class="story-tap-zone-left" id="storyTapLeft" title="Previous story"></div>
      <div class="story-tap-zone-right" id="storyTapRight" title="Next story"></div>

      <!-- Media container: supports Photo and Video -->
      <div class="story-img-container" id="storyMediaContainer">
        <img id="storyViewerImage" src="" alt="Story" style="display:none">
        <video id="storyViewerVideo" playsinline webkit-playsinline loop style="display:none"></video>

        <!-- Instagram Music Sticker on story -->
        <div id="storyViewerMusicSticker" class="story-insta-sticker" style="display:none"></div>
      </div>

      <!-- Floating hearts container for like animations -->
      <div id="storyFloatingHeartsContainer" class="story-floating-hearts-container"></div>

      <div class="story-caption-overlay" id="storyViewerCaptionBox" style="display:none;bottom:64px">
        <p id="storyViewerCaption" style="margin:0"></p>
      </div>

      <!-- Story Reply / Chat Bar (For other users' stories) -->
      <div id="storyViewerChatRow" style="position:absolute;bottom:12px;left:12px;right:12px;z-index:25;display:none;align-items:center;gap:8px">
        <input id="storyReplyTextInput" placeholder="Send a message..." autocomplete="off" style="flex:1;background:rgba(0,0,0,0.55);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,0.3);border-radius:24px;padding:9px 16px;color:#fff;font-size:13px;outline:none">
        <button id="storyReplySendBtn" type="button" style="background:linear-gradient(135deg,#ff4d88,#ff6584);border:none;color:#fff;border-radius:50%;width:38px;height:38px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:15px;flex-shrink:0" title="Reply to story">💬</button>
        <button id="storyLikeBtn" type="button" class="story-heart-btn" title="Like story">
          <span id="storyHeartIcon">🤍</span>
          <span id="storyLikeCount" class="story-like-count" style="display:none">0</span>
        </button>
      </div>

      <!-- Story Owner Activity Bar (Seen by / Viewers & Likes) -->
      <div id="storyViewerActivityRow" class="story-viewer-activity-row" style="display:none">
        <div class="activity-left">
          <span>👁️</span>
          <span>Seen by <b id="storyActivityViewsCount">0</b></span>
          <span style="opacity:0.4">•</span>
          <span style="color:#ff4d88">❤️</span>
          <span><b id="storyActivityLikesCount">0</b> likes</span>
        </div>
        <div class="activity-right">
          <span>Viewers</span>
          <span class="activity-chevron">▲</span>
        </div>
      </div>
    </div>
  </div>

  <!-- STORY VIEWERS MODAL (INSTAGRAM-STYLE) -->
  <div class="modal-backdrop" id="storyViewersModal" style="background:rgba(0,0,0,0.85);z-index:10005">
    <div class="modal-card" style="max-width: 440px; max-height: 80vh; display: flex; flex-direction: column; padding: 0; overflow: hidden; border-radius: 20px; background: var(--card-bg, #1a1a2e); border: 1px solid rgba(255,255,255,0.12); box-shadow: 0 24px 60px rgba(0,0,0,0.8);">
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid rgba(255,255,255,0.08);">
        <div>
          <h3 style="margin: 0; font-size: 16px; font-weight: 700; display:flex; align-items:center; gap:8px;">
            <span>Story Activity</span>
            <span id="viewersModalViewsBadge" class="badge" style="background: rgba(255,77,136,0.18); color: #ff6584; font-size: 11px; font-weight: 600;">0 views</span>
            <span id="viewersModalLikesBadge" class="badge" style="background: rgba(239,68,68,0.18); color: #ef4444; font-size: 11px; font-weight: 600;">0 likes</span>
          </h3>
          <p style="margin: 3px 0 0; font-size: 11px; color: var(--text-muted, #94a3b8)">People who viewed your story</p>
        </div>
        <div class="modal-close" id="closeStoryViewersModal" style="position: static; margin: 0; color: #fff; background: rgba(255,255,255,0.15)">✕</div>
      </div>
      <div id="storyViewersList" style="flex: 1; overflow-y: auto; padding: 14px 16px; min-height: 220px; max-height: 55vh; display: flex; flex-direction: column; gap: 8px;">
        <!-- Filled dynamically -->
      </div>
    </div>
  </div>

  <!-- SNAPCHAT-STYLE AVATAR STUDIO MODAL -->
  <div class="modal-backdrop" id="avatarStudioModal">
    <div class="modal-card" style="max-width: 540px;">
      <div class="modal-close" id="closeAvatarStudio">✕</div>
      <div style="text-align:center;margin-bottom:16px">
        <div class="avatar-preview-box" id="avatarStudioPreview"></div>
        <h2 style="margin:0 0 4px;font-size:22px">Avatar Creator ✨</h2>
        <p style="margin:0;color:var(--muted);font-size:13px">Design your cartoon avatar to display before your username!</p>
        <div style="display:flex;gap:6px;justify-content:center;margin-top:10px;flex-wrap:wrap">
          <button class="mini-btn" id="randomAvatarBtn" type="button" style="background:#fff0f6;border:1px solid #f9c2d8">🎲 Shuffle</button>
          <button class="mini-btn" id="presetRomanticBtn" type="button" style="background:#fff0f6;border:1px solid #f9c2d8">💕 Romantic</button>
          <button class="mini-btn" id="presetCoolBtn" type="button" style="background:#fff0f6;border:1px solid #f9c2d8">😎 Cool</button>
          <button class="mini-btn" id="presetRoyalBtn" type="button" style="background:#fff0f6;border:1px solid #f9c2d8">👑 Royal</button>
        </div>
      </div>

      <div style="max-height: 46vh; overflow-y: auto; padding-right: 6px;">
        <!-- Skin Tone -->
        <div class="studio-group">
          <div class="studio-title">🎨 Skin Tone</div>
          <div class="swatch-row" id="skinSwatches"></div>
        </div>

        <!-- Expression -->
        <div class="studio-group">
          <div class="studio-title">😊 Expression & Eyes</div>
          <div class="chip-grid" id="exprChips"></div>
        </div>

        <!-- Hairstyle -->
        <div class="studio-group">
          <div class="studio-title">💇 Hairstyle</div>
          <div class="chip-grid" id="hairChips"></div>
        </div>

        <!-- Hair Color -->
        <div class="studio-group">
          <div class="studio-title">🎨 Hair Color</div>
          <div class="swatch-row" id="hairColorSwatches"></div>
        </div>

        <!-- Accessories -->
        <div class="studio-group">
          <div class="studio-title">👑 Accessories</div>
          <div class="chip-grid" id="accessoryChips"></div>
        </div>

        <!-- Outfit Style & Color -->
        <div class="studio-group">
          <div class="studio-title">👕 Outfit Style</div>
          <div class="chip-grid" id="outfitChips" style="margin-bottom:8px"></div>
          <div class="swatch-row" id="outfitColorSwatches"></div>
        </div>

        <!-- Background Mood Ring -->
        <div class="studio-group">
          <div class="studio-title">🌈 Background Ring</div>
          <div class="swatch-row" id="bgSwatches"></div>
        </div>
      </div>

      <div style="display:flex;gap:10px;margin-top:18px">
        <button class="btn btn-primary" id="saveAvatarBtn" style="flex:1" type="button">💾 Save & Apply Avatar</button>
        <button class="btn btn-soft" id="cancelAvatarBtn" type="button">Cancel</button>
      </div>
    </div>
  </div>

  <div class="toast" id="toast"></div>

  <script>
    let appState = { auth: { is_authenticated: false }, notifications: [], users: [], requests: [], recently_viewed: [], stats: {} };
    let lastStateHash = '';
    let isSyncing = false;
    let currentTab = 'friends'; // 'friends' or 'discover'
    let currentMainTab = 'connections'; // 'connections', 'feed', or 'chats'
    let activeChatPartner = null;
    let cachedPosts = [];
    let cachedStories = [];
    let storyProgressTimer = null;
    let currentViewingStories = [];
    let currentStoryIndex = 0;
    let selectedPostImageBase64 = null;
    let selectedStoryImageBase64 = null;
    let selectedStoryMediaBase64 = null;
    let selectedStoryMediaType = 'image';
    let selectedStorySong = null;
    let selectedStickerStyle = 'card';
    let previewAudioElement = new Audio();
    let currentPreviewSongId = null;
    let viewerAudioElement = new Audio();
    let isStoryMuted = false;
    let isStoryPaused = false;
    let storyRemainingTime = 0;
    let storyTotalDuration = 5000;
    let storyStartTime = 0;
    let authToken = localStorage.getItem('loveloop_token') || '';

    const $ = (selector) => document.querySelector(selector);
    const initials = (name) => (name || '?').slice(0, 1).toUpperCase();

    async function request(url, options = {}) {
      const headers = { 'Content-Type': 'application/json', ...options.headers };
      if (authToken) headers['X-Auth-Token'] = authToken;
      const response = await fetch(url, { ...options, headers });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Something went wrong.');
      return data;
    }

    function showToast(message, isError = false) {
      const toast = $('#toast');
      toast.textContent = message;
      toast.className = `toast show${isError ? ' error' : ''}`;
      clearTimeout(window.toastTimer);
      window.toastTimer = setTimeout(() => toast.className = 'toast', 3500);
    }

    function escapeHtml(value) {
      return String(value || '').replace(/[&<>"']/g, char => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#039;' }[char]));
    }
    const escapeAttr = escapeHtml;

    // Helper: Client-side image compression
    function compressImage(file, maxDim = 800, quality = 0.75) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => {
          const img = new Image();
          img.onload = () => {
            let w = img.width;
            let h = img.height;
            if (w > maxDim || h > maxDim) {
              if (w > h) {
                h = Math.round((h * maxDim) / w);
                w = maxDim;
              } else {
                w = Math.round((w * maxDim) / h);
                h = maxDim;
              }
            }
            const canvas = document.createElement('canvas');
            canvas.width = w;
            canvas.height = h;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, w, h);
            resolve(canvas.toDataURL('image/jpeg', quality));
          };
          img.onerror = () => reject(new Error('Invalid image file format.'));
          img.src = e.target.result;
        };
        reader.onerror = () => reject(new Error('Failed reading file.'));
        reader.readAsDataURL(file);
      });
    }

    // --- SNAPCHAT-STYLE AVATAR ENGINE & STUDIO ---
    let currentEditingAvatar = null;

    function hashCode(str) {
      let hash = 0;
      for (let i = 0; i < (str || '').length; i++) {
        hash = ((hash << 5) - hash) + str.charCodeAt(i);
        hash |= 0;
      }
      return Math.abs(hash);
    }

    const AVATAR_OPTIONS = {
      skins: [
        { id: '#ffdfc4', name: 'Fair' },
        { id: '#f3cbb0', name: 'Peach' },
        { id: '#e8b896', name: 'Golden' },
        { id: '#c9976f', name: 'Warm Olive' },
        { id: '#a86f44', name: 'Caramel' },
        { id: '#7a4622', name: 'Rich Deep' }
      ],
      hairColors: [
        { id: '#1f1b24', name: 'Jet Black' },
        { id: '#4a2e1b', name: 'Espresso Brown' },
        { id: '#875129', name: 'Chestnut' },
        { id: '#c98a3c', name: 'Honey Blonde' },
        { id: '#a82c2c', name: 'Ruby Auburn' },
        { id: '#ff5c98', name: 'Pastel Pink' },
        { id: '#7b3fe4', name: 'Electric Purple' },
        { id: '#20b2aa', name: 'Neon Mint' }
      ],
      hairStyles: [
        { id: 'wavy', label: '🌊 Wavy' },
        { id: 'curly', label: '🌀 Curly' },
        { id: 'bob', label: '💇 Chic Bob' },
        { id: 'spikes', label: '⚡ Spiky' },
        { id: 'bun', label: '🎀 Top Bun' },
        { id: 'slick', label: '✨ Side Part' },
        { id: 'buzz', label: '✂️ Buzz Cut' },
        { id: 'afro', label: '👑 Soft Afro' }
      ],
      expressions: [
        { id: 'heart_eyes', label: '😍 Heart Eyes' },
        { id: 'shades', label: '😎 Cool Shades' },
        { id: 'wink', label: '😉 Winking' },
        { id: 'sparkle', label: '✨ Star Eyes' },
        { id: 'happy', label: '😊 Big Smile' },
        { id: 'goofy', label: '😜 Tongue Out' },
        { id: 'blush', label: '🥰 Blushing' },
        { id: 'chill', label: '😌 Chill' }
      ],
      accessories: [
        { id: 'none', label: '🚫 None' },
        { id: 'flower', label: '🌸 Flower' },
        { id: 'shades_heart', label: '💕 Heart Shades' },
        { id: 'crown', label: '👑 Gold Crown' },
        { id: 'cap', label: '🧢 Snapback' },
        { id: 'bow', label: '🎀 Hair Bow' },
        { id: 'headphones', label: '🎧 Headphones' },
        { id: 'star_cheeks', label: '⭐ Cheek Stars' }
      ],
      outfits: [
        { id: 'hoodie', label: '🧥 Street Hoodie' },
        { id: 'tee', label: '👕 Casual Tee' },
        { id: 'collar', label: '👔 Formal Collar' },
        { id: 'sweater', label: '🧶 Knit Sweater' },
        { id: 'jacket', label: '🕶️ Biker Jacket' }
      ],
      outfitColors: [
        { id: '#ff4d88', name: 'Hot Pink' },
        { id: '#845ec2', name: 'Lavender' },
        { id: '#2c73d2', name: 'Royal Blue' },
        { id: '#00c9a7', name: 'Teal Mint' },
        { id: '#ff9671', name: 'Peach Glow' },
        { id: '#ffc75f', name: 'Sunflower' },
        { id: '#2b2d42', name: 'Midnight' },
        { id: '#ffffff', name: 'Pure White' }
      ],
      backgrounds: [
        { id: 'snapchat', name: 'Sunny Yellow', colors: ['#fffc00', '#ffd200'] },
        { id: 'pink', name: 'Love Pink', colors: ['#ff6584', '#f38ba8'] },
        { id: 'sunset', name: 'Sunset Peach', colors: ['#ff7e5f', '#feb47b'] },
        { id: 'ocean', name: 'Aqua Blue', colors: ['#4facfe', '#00f2fe'] },
        { id: 'lavender', name: 'Neon Purple', colors: ['#9b51e0', '#e0c3fc'] },
        { id: 'emerald', name: 'Mint Glow', colors: ['#0ba360', '#3cba92'] },
        { id: 'midnight', name: 'Dark Nebula', colors: ['#1e130c', '#9a8478'] }
      ]
    };

    function getDefaultAvatar(username) {
      const h = hashCode(username || 'user');
      const s = AVATAR_OPTIONS.skins;
      const hc = AVATAR_OPTIONS.hairColors;
      const hs = AVATAR_OPTIONS.hairStyles;
      const ex = AVATAR_OPTIONS.expressions;
      const ac = AVATAR_OPTIONS.accessories;
      const ot = AVATAR_OPTIONS.outfits;
      const oc = AVATAR_OPTIONS.outfitColors;
      const bg = AVATAR_OPTIONS.backgrounds;

      return {
        skin: s[h % s.length].id,
        hairColor: hc[(h >> 2) % hc.length].id,
        hairStyle: hs[(h >> 4) % hs.length].id,
        expression: ex[(h >> 6) % ex.length].id,
        accessory: ac[(h >> 8) % ac.length].id,
        outfit: ot[(h >> 10) % ot.length].id,
        outfitColor: oc[(h >> 12) % oc.length].id,
        bg: bg[(h >> 14) % bg.length].id
      };
    }

    function renderAvatar(avatarConfig, username, size = 44, profilePhoto = null) {
      if (profilePhoto) {
        return `<div style="width:${size}px;height:${size}px;border-radius:50%;overflow:hidden;box-shadow:0 3px 8px rgba(0,0,0,0.14);display:inline-block;vertical-align:middle;flex-shrink:0;border:1.5px solid rgba(255,255,255,0.8)"><img src="${escapeAttr(profilePhoto)}" alt="${escapeAttr(username)}" style="width:100%;height:100%;object-fit:cover;display:block;"></div>`;
      }
      let cfg = avatarConfig;
      if (!cfg || typeof cfg !== 'object') {
        cfg = getDefaultAvatar(username);
      } else {
        const def = getDefaultAvatar(username);
        cfg = { ...def, ...cfg };
      }

      const uid = 'av_' + Math.abs(hashCode((username || 'user') + '_' + size + '_' + JSON.stringify(cfg)));
      const bgObj = AVATAR_OPTIONS.backgrounds.find(b => b.id === cfg.bg) || AVATAR_OPTIONS.backgrounds[0];
      const bg1 = bgObj.colors[0];
      const bg2 = bgObj.colors[1];
      const skin = cfg.skin || '#ffdfc4';
      const hairColor = cfg.hairColor || '#1f1b24';
      const hairStyle = cfg.hairStyle || 'wavy';
      const expression = cfg.expression || 'happy';
      const accessory = cfg.accessory || 'none';
      const outfit = cfg.outfit || 'hoodie';
      const outfitColor = cfg.outfitColor || '#ff4d88';

      let outfitExtra = '';
      if (outfit === 'hoodie') {
        outfitExtra = `
          <path d="M 38 70 Q 50 82 62 70" fill="none" stroke="rgba(0,0,0,0.18)" stroke-width="3.5" stroke-linecap="round"/>
          <line x1="44" y1="74" x2="44" y2="85" stroke="#fff" stroke-width="1.8" opacity="0.85"/>
          <circle cx="44" cy="85" r="2" fill="#fff" opacity="0.85"/>
          <line x1="56" y1="74" x2="56" y2="88" stroke="#fff" stroke-width="1.8" opacity="0.85"/>
          <circle cx="56" cy="88" r="2" fill="#fff" opacity="0.85"/>
        `;
      } else if (outfit === 'tee') {
        outfitExtra = `<path d="M 36 70 Q 50 80 64 70" fill="none" stroke="rgba(255,255,255,0.6)" stroke-width="3" stroke-linecap="round"/>`;
      } else if (outfit === 'collar') {
        outfitExtra = `
          <polygon points="40,70 50,83 45,70" fill="#fff" opacity="0.95"/>
          <polygon points="60,70 50,83 55,70" fill="#fff" opacity="0.95"/>
          <polygon points="48,74 52,74 51,94 49,94" fill="#d81b60"/>
        `;
      } else if (outfit === 'sweater') {
        outfitExtra = `
          <path d="M 36 70 Q 50 78 64 70" fill="none" stroke="rgba(0,0,0,0.2)" stroke-width="4"/>
          <line x1="38" y1="71" x2="38" y2="76" stroke="rgba(0,0,0,0.15)" stroke-width="1.5"/>
          <line x1="44" y1="73" x2="44" y2="78" stroke="rgba(0,0,0,0.15)" stroke-width="1.5"/>
          <line x1="50" y1="74" x2="50" y2="79" stroke="rgba(0,0,0,0.15)" stroke-width="1.5"/>
          <line x1="56" y1="73" x2="56" y2="78" stroke="rgba(0,0,0,0.15)" stroke-width="1.5"/>
          <line x1="62" y1="71" x2="62" y2="76" stroke="rgba(0,0,0,0.15)" stroke-width="1.5"/>
        `;
      } else if (outfit === 'jacket') {
        outfitExtra = `
          <path d="M 42 70 L 50 88 L 58 70" fill="#222" opacity="0.25"/>
          <path d="M 32 70 L 44 86 L 24 100" fill="rgba(0,0,0,0.2)"/>
          <path d="M 68 70 L 56 86 L 76 100" fill="rgba(0,0,0,0.2)"/>
        `;
      }

      let exprSvg = '';
      if (expression === 'heart_eyes') {
        exprSvg = `
          <g transform="translate(39, 45) scale(0.65)">
            <path d="M 0 0 C -6 -8 -16 -4 -16 5 C -16 13 0 22 0 26 C 0 22 16 13 16 5 C 16 -4 6 -8 0 0 Z" fill="#ff1a60" stroke="#b30036" stroke-width="1.5"/>
            <circle cx="-4" cy="4" r="2" fill="#fff" opacity="0.8"/>
          </g>
          <g transform="translate(61, 45) scale(0.65)">
            <path d="M 0 0 C -6 -8 -16 -4 -16 5 C -16 13 0 22 0 26 C 0 22 16 13 16 5 C 16 -4 6 -8 0 0 Z" fill="#ff1a60" stroke="#b30036" stroke-width="1.5"/>
            <circle cx="-4" cy="4" r="2" fill="#fff" opacity="0.8"/>
          </g>
          <path d="M 43 59 Q 50 67 57 59" fill="#7a1c32" stroke="#7a1c32" stroke-width="1"/>
          <path d="M 45 59.5 Q 50 61.5 55 59.5" fill="#fff"/>
        `;
      } else if (expression === 'shades') {
        exprSvg = `
          <path d="M 28 41 Q 50 43 72 41 L 70 51 Q 62 57 52 52 Q 42 57 30 51 Z" fill="#18181b" stroke="#000" stroke-width="1.5"/>
          <line x1="33" y1="44" x2="44" y2="49" stroke="#fff" stroke-width="1.5" opacity="0.6" stroke-linecap="round"/>
          <line x1="56" y1="44" x2="67" y2="49" stroke="#fff" stroke-width="1.5" opacity="0.6" stroke-linecap="round"/>
          <rect x="48" y="43" width="4" height="2" fill="#18181b"/>
          <path d="M 44 59 Q 51 63 56 58" fill="none" stroke="#7a1c32" stroke-width="2.2" stroke-linecap="round"/>
        `;
      } else if (expression === 'wink') {
        exprSvg = `
          <ellipse cx="38" cy="46" rx="4" ry="4.5" fill="#2b2d42"/>
          <circle cx="36.5" cy="44.5" r="1.5" fill="#fff"/>
          <path d="M 58 47 Q 63 42 68 47" fill="none" stroke="#2b2d42" stroke-width="2.8" stroke-linecap="round"/>
          <path d="M 44 59 Q 51 63 56 58" fill="none" stroke="#7a1c32" stroke-width="2.2" stroke-linecap="round"/>
        `;
      } else if (expression === 'sparkle') {
        exprSvg = `
          <ellipse cx="38" cy="46" rx="5" ry="6" fill="#1e1b4b"/>
          <ellipse cx="62" cy="46" rx="5" ry="6" fill="#1e1b4b"/>
          <circle cx="36" cy="43.5" r="2.2" fill="#fff"/>
          <circle cx="40" cy="48" r="1.2" fill="#fff"/>
          <circle cx="60" cy="43.5" r="2.2" fill="#fff"/>
          <circle cx="64" cy="48" r="1.2" fill="#fff"/>
          <path d="M 44 59 Q 50 65 56 59" fill="none" stroke="#bd2850" stroke-width="2.4" stroke-linecap="round"/>
        `;
      } else if (expression === 'happy') {
        exprSvg = `
          <ellipse cx="38" cy="46" rx="4" ry="4" fill="#2b2d42"/>
          <circle cx="36.5" cy="44.5" r="1.5" fill="#fff"/>
          <ellipse cx="62" cy="46" rx="4" ry="4" fill="#2b2d42"/>
          <circle cx="60.5" cy="44.5" r="1.5" fill="#fff"/>
          <path d="M 43 59 Q 50 67 57 59" fill="#7a1c32" stroke="#7a1c32" stroke-width="1"/>
          <path d="M 45 59.5 Q 50 61.5 55 59.5" fill="#fff"/>
        `;
      } else if (expression === 'goofy') {
        exprSvg = `
          <circle cx="38" cy="45" r="5" fill="#fff" stroke="#222" stroke-width="1.5"/>
          <circle cx="38" cy="45" r="2.5" fill="#222"/>
          <circle cx="37" cy="44" r="1" fill="#fff"/>
          <path d="M 58 47 Q 63 41 68 47" fill="none" stroke="#222" stroke-width="2.5" stroke-linecap="round"/>
          <path d="M 44 59 Q 50 64 56 59 Z" fill="#7a1c32"/>
          <path d="M 46 61 Q 50 71 54 61 Z" fill="#ff4d79"/>
        `;
      } else if (expression === 'blush') {
        exprSvg = `
          <path d="M 33 46 Q 38 41 43 46" fill="none" stroke="#2b2d42" stroke-width="2.6" stroke-linecap="round"/>
          <path d="M 57 46 Q 62 41 67 46" fill="none" stroke="#2b2d42" stroke-width="2.6" stroke-linecap="round"/>
          <path d="M 44 59 Q 50 65 56 59" fill="none" stroke="#bd2850" stroke-width="2.4" stroke-linecap="round"/>
        `;
      } else { // chill
        exprSvg = `
          <path d="M 33 45 Q 38 43 43 45" fill="none" stroke="#2b2d42" stroke-width="2.4" stroke-linecap="round"/>
          <circle cx="38" cy="46.5" r="2" fill="#2b2d42"/>
          <path d="M 57 45 Q 62 43 67 45" fill="none" stroke="#2b2d42" stroke-width="2.4" stroke-linecap="round"/>
          <circle cx="62" cy="46.5" r="2" fill="#2b2d42"/>
          <path d="M 44 59 Q 51 63 56 58" fill="none" stroke="#7a1c32" stroke-width="2.2" stroke-linecap="round"/>
        `;
      }

      let hairBack = '';
      let hairFront = '';
      if (hairStyle === 'wavy') {
        hairBack = `
          <path d="M 23 44 C 20 62 25 72 30 76 C 33 70 33 55 31 46 Z" fill="${hairColor}"/>
          <path d="M 77 44 C 80 62 75 72 70 76 C 67 70 67 55 69 46 Z" fill="${hairColor}"/>
        `;
        hairFront = `
          <path d="M 26 44 Q 24 23 50 22 Q 76 23 74 44 Q 68 28 50 28 Q 32 28 26 44 Z" fill="${hairColor}"/>
          <path d="M 28 35 Q 40 27 52 35 Q 64 27 72 35 Q 68 40 50 33 Q 32 40 28 35 Z" fill="${hairColor}"/>
        `;
      } else if (hairStyle === 'curly') {
        hairFront = `
          <path d="M 25 45 C 20 35 25 22 36 22 C 41 18 50 18 56 21 C 65 18 76 25 76 36 C 81 44 76 56 73 62 C 68 64 65 56 68 48 C 68 35 60 28 50 28 C 40 28 32 35 32 48 C 35 56 32 64 27 62 C 24 56 20 48 25 45 Z" fill="${hairColor}"/>
          <circle cx="34" cy="28" r="6" fill="${hairColor}"/>
          <circle cx="45" cy="25" r="6.5" fill="${hairColor}"/>
          <circle cx="56" cy="25" r="6.5" fill="${hairColor}"/>
          <circle cx="66" cy="28" r="6" fill="${hairColor}"/>
        `;
      } else if (hairStyle === 'bob') {
        hairFront = `
          <path d="M 24 45 L 24 62 Q 28 66 32 60 L 30 44 Q 31 24 50 24 Q 69 24 70 44 L 68 60 Q 72 66 76 62 L 76 45 Q 78 22 50 21 Q 22 22 24 45 Z" fill="${hairColor}"/>
          <path d="M 27 34 Q 50 38 73 34 L 72 39 Q 50 43 28 39 Z" fill="${hairColor}"/>
        `;
      } else if (hairStyle === 'spikes') {
        hairFront = `
          <path d="M 26 42 L 21 33 L 30 30 L 28 19 L 40 22 L 44 13 L 54 17 L 62 12 L 64 22 L 74 20 L 71 32 L 79 36 L 72 44 Q 71 27 50 27 Q 29 27 26 42 Z" fill="${hairColor}"/>
          <polygon points="38,28 42,39 46,30" fill="${hairColor}"/>
          <polygon points="46,29 50,40 54,30" fill="${hairColor}"/>
          <polygon points="54,29 58,38 62,31" fill="${hairColor}"/>
        `;
      } else if (hairStyle === 'bun') {
        hairBack = `
          <circle cx="50" cy="18" r="10" fill="${hairColor}"/>
          <ellipse cx="50" cy="19" rx="11" ry="8" fill="${hairColor}"/>
        `;
        hairFront = `
          <path d="M 26 44 Q 24 25 50 24 Q 76 25 74 44 Q 68 30 50 30 Q 32 30 26 44 Z" fill="${hairColor}"/>
          <path d="M 28 45 Q 26 56 30 60" stroke="${hairColor}" stroke-width="2.5" fill="none" stroke-linecap="round"/>
          <path d="M 72 45 Q 74 56 70 60" stroke="${hairColor}" stroke-width="2.5" fill="none" stroke-linecap="round"/>
        `;
      } else if (hairStyle === 'slick') {
        hairFront = `<path d="M 26 44 Q 25 24 50 23 Q 75 24 74 44 Q 70 28 55 28 Q 38 27 28 36 Z" fill="${hairColor}"/>`;
      } else if (hairStyle === 'afro') {
        hairBack = `<ellipse cx="50" cy="42" rx="28" ry="25" fill="${hairColor}"/>`;
        hairFront = `
          <circle cx="35" cy="27" r="7" fill="${hairColor}"/>
          <circle cx="50" cy="25" r="7" fill="${hairColor}"/>
          <circle cx="65" cy="27" r="7" fill="${hairColor}"/>
        `;
      } else { // buzz
        hairFront = `<path d="M 26 44 Q 24 23 50 22 Q 76 23 74 44 Q 71 27 50 26 Q 29 27 26 44 Z" fill="${hairColor}"/>`;
      }

      let accSvg = '';
      if (accessory === 'flower') {
        accSvg = `
          <g transform="translate(68, 29)">
            <circle cx="0" cy="-6" r="3.8" fill="#ffffff"/>
            <circle cx="6" cy="-2" r="3.8" fill="#ffffff"/>
            <circle cx="4" cy="5" r="3.8" fill="#ffffff"/>
            <circle cx="-4" cy="5" r="3.8" fill="#ffffff"/>
            <circle cx="-6" cy="-2" r="3.8" fill="#ffffff"/>
            <circle cx="0" cy="0" r="3.6" fill="#ffd000"/>
          </g>
        `;
      } else if (accessory === 'shades_heart') {
        accSvg = `
          <g transform="translate(38, 47) scale(0.68)">
            <path d="M 0 0 C -7 -9 -18 -5 -18 6 C -18 15 0 25 0 29 C 0 25 18 15 18 6 C 18 -5 7 -9 0 0 Z" fill="rgba(255, 45, 120, 0.75)" stroke="#ff1a60" stroke-width="2"/>
            <line x1="-8" y1="5" x2="0" y2="15" stroke="#fff" stroke-width="2" opacity="0.8" stroke-linecap="round"/>
          </g>
          <g transform="translate(62, 47) scale(0.68)">
            <path d="M 0 0 C -7 -9 -18 -5 -18 6 C -18 15 0 25 0 29 C 0 25 18 15 18 6 C 18 -5 7 -9 0 0 Z" fill="rgba(255, 45, 120, 0.75)" stroke="#ff1a60" stroke-width="2"/>
            <line x1="-8" y1="5" x2="0" y2="15" stroke="#fff" stroke-width="2" opacity="0.8" stroke-linecap="round"/>
          </g>
          <path d="M 44 46 Q 50 43 56 46" fill="none" stroke="#ff1a60" stroke-width="2.5"/>
          <line x1="26" y1="46" x2="33" y2="47" stroke="#ff1a60" stroke-width="2"/>
          <line x1="67" y1="47" x2="74" y2="46" stroke="#ff1a60" stroke-width="2"/>
        `;
      } else if (accessory === 'crown') {
        accSvg = `
          <polygon points="34,26 38,15 44,22 50,12 56,22 62,15 66,26" fill="#ffd700" stroke="#d4af37" stroke-width="1.2"/>
          <rect x="34" y="25" width="32" height="4" rx="2" fill="#ffd700" stroke="#d4af37" stroke-width="1"/>
          <circle cx="50" cy="13" r="2.2" fill="#ff2a6d"/>
          <circle cx="38" cy="16" r="1.6" fill="#00d2ff"/>
          <circle cx="62" cy="16" r="1.6" fill="#00d2ff"/>
          <circle cx="50" cy="27" r="1.2" fill="#fff"/>
          <circle cx="42" cy="27" r="1" fill="#fff"/>
          <circle cx="58" cy="27" r="1" fill="#fff"/>
        `;
      } else if (accessory === 'cap') {
        accSvg = `
          <path d="M 25 36 Q 26 21 50 19 Q 74 21 75 36 Z" fill="#2b2d42"/>
          <path d="M 23 35 Q 50 31 77 35 Q 82 40 68 40 Q 50 38 23 35 Z" fill="#ff4d79"/>
          <circle cx="50" cy="19" r="2.2" fill="#ff4d79"/>
        `;
      } else if (accessory === 'bow') {
        accSvg = `
          <g transform="translate(32, 28) rotate(-15)">
            <polygon points="0,0 -10,-8 -10,8" fill="#ff4d79"/>
            <polygon points="0,0 10,-8 10,8" fill="#ff4d79"/>
            <circle cx="0" cy="0" r="3.5" fill="#ff2a6d"/>
          </g>
        `;
      } else if (accessory === 'headphones') {
        accSvg = `
          <path d="M 22 50 Q 20 17 50 17 Q 80 17 78 50" fill="none" stroke="#2b2d42" stroke-width="4.5" stroke-linecap="round"/>
          <rect x="18" y="43" width="7" height="16" rx="3.5" fill="#ff4d79" stroke="#2b2d42" stroke-width="1.5"/>
          <rect x="75" y="43" width="7" height="16" rx="3.5" fill="#ff4d79" stroke="#2b2d42" stroke-width="1.5"/>
        `;
      } else if (accessory === 'star_cheeks') {
        accSvg = `
          <polygon points="36,51 37,53 39.5,53.5 37.5,55.5 38,58 36,56.5 34,58 34.5,55.5 32.5,53.5 35,53" fill="#ffd700" stroke="#e6b800" stroke-width="0.5"/>
          <polygon points="64,51 65,53 67.5,53.5 65.5,55.5 66,58 64,56.5 62,58 62.5,55.5 60.5,53.5 63,53" fill="#ffd700" stroke="#e6b800" stroke-width="0.5"/>
        `;
      }

      return `
        <svg viewBox="0 0 100 100" width="${size}" height="${size}" xmlns="http://www.w3.org/2000/svg" style="border-radius:50%;display:block;user-select:none;">
          <defs>
            <linearGradient id="${uid}_bg" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="${bg1}" />
              <stop offset="100%" stop-color="${bg2}" />
            </linearGradient>
          </defs>
          <circle cx="50" cy="50" r="50" fill="url(#${uid}_bg)" />
          <circle cx="50" cy="50" r="48.5" fill="none" stroke="rgba(255,255,255,0.4)" stroke-width="2" />
          ${hairBack}
          <path d="M 12 100 Q 18 72 40 70 L 60 70 Q 82 72 88 100 Z" fill="${outfitColor}" />
          ${outfitExtra}
          <rect x="43" y="60" width="14" height="14" rx="4" fill="${skin}" />
          <path d="M 43 64 Q 50 68 57 64" fill="none" stroke="rgba(0,0,0,0.1)" stroke-width="2" />
          <ellipse cx="27" cy="51" rx="4.5" ry="6.5" fill="${skin}" />
          <ellipse cx="27" cy="51" rx="2" ry="3.5" fill="rgba(0,0,0,0.08)" />
          <ellipse cx="73" cy="51" rx="4.5" ry="6.5" fill="${skin}" />
          <ellipse cx="73" cy="51" rx="2" ry="3.5" fill="rgba(0,0,0,0.08)" />
          <ellipse cx="50" cy="49" rx="23" ry="25" fill="${skin}" />
          <ellipse cx="36" cy="54" rx="4.5" ry="3" fill="#ff4d79" opacity="0.35" />
          <ellipse cx="64" cy="54" rx="4.5" ry="3" fill="#ff4d79" opacity="0.35" />
          <path d="M 48.5 50 Q 50 53 51.5 51" fill="none" stroke="rgba(0,0,0,0.22)" stroke-width="1.8" stroke-linecap="round"/>
          <path d="M 33 40 Q 40 37 45 41" fill="none" stroke="${hairColor}" stroke-width="2.2" stroke-linecap="round"/>
          <path d="M 67 40 Q 60 37 55 41" fill="none" stroke="${hairColor}" stroke-width="2.2" stroke-linecap="round"/>
          ${exprSvg}
          ${hairFront}
          ${accSvg}
          <ellipse cx="50" cy="50" rx="49" ry="49" fill="none" stroke="rgba(255,255,255,0.2)" stroke-width="1.5" />
        </svg>
      `;
    }

    function buildAvatarStudioControls() {
      if (!currentEditingAvatar) return;

      $('#skinSwatches').innerHTML = AVATAR_OPTIONS.skins.map(s => `
        <button class="swatch-btn ${currentEditingAvatar.skin === s.id ? 'active' : ''}" type="button" data-prop="skin" data-val="${s.id}" title="${s.name}" style="background:${s.id}"></button>
      `).join('');

      $('#exprChips').innerHTML = AVATAR_OPTIONS.expressions.map(e => `
        <button class="chip-btn ${currentEditingAvatar.expression === e.id ? 'active' : ''}" type="button" data-prop="expression" data-val="${e.id}">${e.label}</button>
      `).join('');

      $('#hairChips').innerHTML = AVATAR_OPTIONS.hairStyles.map(h => `
        <button class="chip-btn ${currentEditingAvatar.hairStyle === h.id ? 'active' : ''}" type="button" data-prop="hairStyle" data-val="${h.id}">${h.label}</button>
      `).join('');

      $('#hairColorSwatches').innerHTML = AVATAR_OPTIONS.hairColors.map(c => `
        <button class="swatch-btn ${currentEditingAvatar.hairColor === c.id ? 'active' : ''}" type="button" data-prop="hairColor" data-val="${c.id}" title="${c.name}" style="background:${c.id}"></button>
      `).join('');

      $('#accessoryChips').innerHTML = AVATAR_OPTIONS.accessories.map(a => `
        <button class="chip-btn ${currentEditingAvatar.accessory === a.id ? 'active' : ''}" type="button" data-prop="accessory" data-val="${a.id}">${a.label}</button>
      `).join('');

      $('#outfitChips').innerHTML = AVATAR_OPTIONS.outfits.map(o => `
        <button class="chip-btn ${currentEditingAvatar.outfit === o.id ? 'active' : ''}" type="button" data-prop="outfit" data-val="${o.id}">${o.label}</button>
      `).join('');

      $('#outfitColorSwatches').innerHTML = AVATAR_OPTIONS.outfitColors.map(c => `
        <button class="swatch-btn ${currentEditingAvatar.outfitColor === c.id ? 'active' : ''}" type="button" data-prop="outfitColor" data-val="${c.id}" title="${c.name}" style="background:${c.id}"></button>
      `).join('');

      $('#bgSwatches').innerHTML = AVATAR_OPTIONS.backgrounds.map(b => `
        <button class="swatch-btn ${currentEditingAvatar.bg === b.id ? 'active' : ''}" type="button" data-prop="bg" data-val="${b.id}" title="${b.name}" style="background:linear-gradient(135deg, ${b.colors[0]}, ${b.colors[1]})"></button>
      `).join('');
    }

    function updateStudioPreview() {
      const username = (appState.auth && appState.auth.username) || 'you';
      $('#avatarStudioPreview').innerHTML = renderAvatar(currentEditingAvatar, username, 108);
      buildAvatarStudioControls();
    }

    function openAvatarStudio() {
      const auth = appState.auth || {};
      const profile = auth.profile || {};
      const existing = profile.avatar || getDefaultAvatar(auth.username);
      currentEditingAvatar = { ...existing };
      updateStudioPreview();
      $('#avatarStudioModal').classList.add('open');
    }

    function closeAvatarStudioModal() {
      $('#avatarStudioModal').classList.remove('open');
    }

    // --- ANIMATED GRADIENT BACKGROUND (Breathing effect) ---
    (function initAnimatedGradient() {
      const gradientColors = ["#0A0A0A", "#2979FF", "#FF80AB", "#FF6D00", "#FFD600", "#00E676", "#3D5AFE"];
      const gradientStops = [35, 50, 60, 70, 80, 90, 100];
      const startingGap = 115;
      const breathingRange = 8;
      const animationSpeed = 0.03;
      let width = startingGap;
      let directionWidth = 1;

      function step() {
        if (width >= startingGap + breathingRange) directionWidth = -1;
        if (width <= startingGap - breathingRange) directionWidth = 1;
        width += directionWidth * animationSpeed;

        const stopsStr = gradientStops.map((stop, idx) => `${gradientColors[idx]} ${stop}%`).join(', ');
        const el = document.getElementById('authGradientBg');
        if (el) {
          el.style.background = `radial-gradient(${width.toFixed(2)}% ${(width + 12).toFixed(2)}% at 50% 25%, ${stopsStr})`;
        }
        requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    })();

    // --- INTERACTIVE PASSWORD STRENGTH EVALUATOR FOR SIGN UP ---
    const COMMON_PW = /^(?:password|passw0rd|qwerty|letmein|welcome|admin|iloveyou|monkey|dragon|abc123|111111|123123|123456)/i;
    const RUN_PW = /(.)\1{3,}/;
    const RUN_UP_PW = /(?:0123|1234|2345|3456|4567|5678|6789|abcd|bcde|cdef|defg|qwer|wert|erty|asdf)/i;
    const SYMBOL_PW = /[!-/:-@[-`{-~]/;

    function evaluatePassword(val) {
      const rules = [
        { id: 'ruleLength', met: val.length >= 12 },
        { id: 'ruleCase', met: /[a-z]/.test(val) && /[A-Z]/.test(val) },
        { id: 'ruleDigit', met: /\d/.test(val) },
        { id: 'ruleSymbol', met: SYMBOL_PW.test(val) }
      ];
      const passed = rules.filter(r => r.met).length;
      const guessable = val.length > 0 && (COMMON_PW.test(val) || RUN_PW.test(val) || RUN_UP_PW.test(val));
      const score = val.length === 0 ? 0 : (guessable ? 1 : Math.min(4, Math.max(1, passed)));
      return { rules, score, guessable, length: val.length };
    }

    function updatePasswordStrengthUI(val) {
      const { rules, score, guessable, length } = evaluatePassword(val);
      const labels = ['Empty', 'Weak', 'Fair', 'Good', 'Strong'];
      const labelEl = document.getElementById('strengthLabel');
      const warningEl = document.getElementById('strengthWarning');

      let color = '#94a3b8';
      if (score === 1) color = '#ef4444';
      else if (score === 2) color = '#f59e0b';
      else if (score >= 3) color = '#10b981';

      if (labelEl) {
        labelEl.textContent = length === 0 ? 'Empty' : (labels[score] || 'Weak');
        labelEl.style.color = length === 0 ? '#94a3b8' : color;
      }
      if (warningEl) {
        warningEl.style.display = guessable ? 'inline' : 'none';
      }

      for (let i = 0; i < 4; i++) {
        const fillEl = document.getElementById(`meterFill${i}`);
        if (fillEl) {
          if (i < score) {
            fillEl.style.width = '100%';
            fillEl.style.backgroundColor = color;
          } else {
            fillEl.style.width = '0%';
            fillEl.style.backgroundColor = '#e8ebf2';
          }
        }
      }

      rules.forEach(r => {
        const el = document.getElementById(r.id);
        if (el) {
          if (r.met) el.classList.add('met');
          else el.classList.remove('met');
        }
      });
    }

    setTimeout(() => {
      const regPass = document.getElementById('regPasswordInput');
      if (regPass) {
        regPass.addEventListener('input', (e) => updatePasswordStrengthUI(e.target.value));
      }
    }, 100);

    // --- TAB SWITCHING IN LOGIN PORTAL ---
    document.querySelectorAll('.auth-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const activeTab = tab.dataset.tab;
        $('#userLoginForm').style.display = activeTab === 'user-login' ? 'block' : 'none';
        $('#adminLoginForm').style.display = activeTab === 'admin-login' ? 'block' : 'none';
        $('#registerForm').style.display = activeTab === 'register' ? 'block' : 'none';
        if (activeTab === 'register') {
          const inp = document.getElementById('regPasswordInput');
          updatePasswordStrengthUI(inp ? inp.value : '');
        }
      });
    });

    // --- LOGIN & REGISTER HANDLERS ---
    $('#userLoginForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const data = Object.fromEntries(new FormData(e.target));
        data.role = 'user';
        const res = await request('/api/login', { method: 'POST', body: JSON.stringify(data) });
        authToken = res.token;
        localStorage.setItem('loveloop_token', authToken);
        showToast(res.message);
        await refresh();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    $('#adminLoginForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const data = Object.fromEntries(new FormData(e.target));
        data.role = 'admin';
        const res = await request('/api/login', { method: 'POST', body: JSON.stringify(data) });
        authToken = res.token;
        localStorage.setItem('loveloop_token', authToken);
        showToast(res.message);
        await refresh();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    $('#registerForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const data = Object.fromEntries(new FormData(e.target));
        const res = await request('/api/register', { method: 'POST', body: JSON.stringify(data) });
        authToken = res.token;
        localStorage.setItem('loveloop_token', authToken);
        showToast(res.message);
        await refresh();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    $('#logoutBtn').addEventListener('click', async () => {
      try {
        await request('/api/logout', { method: 'POST', body: '{}' });
      } catch (e) {}
      authToken = '';
      localStorage.removeItem('loveloop_token');
      showToast('Logged out.');
      await refresh();
    });

    // --- NOTIFICATION PANEL TOGGLE & CLEAR ---
    $('#notifBtn').addEventListener('click', (e) => {
      e.stopPropagation();
      $('#notifPanel').classList.toggle('open');
    });

    document.addEventListener('click', (e) => {
      if (!e.target.closest('#notifPanel') && !e.target.closest('#notifBtn')) {
        $('#notifPanel').classList.remove('open');
      }
    });

    $('#clearNotifsBtn').addEventListener('click', async () => {
      try {
        await request('/api/notifications/clear', { method: 'POST', body: '{}' });
        showToast('Notifications cleared.');
        await refresh();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // --- USER TABS: MY FRIENDS VS DISCOVER ---
    $('#tabMyFriends').addEventListener('click', () => {
      currentTab = 'friends';
      $('#tabMyFriends').classList.add('active');
      $('#tabDiscover').classList.remove('active');
      $('#gridEyebrow').textContent = 'Your Circle';
      $('#gridTitle').textContent = 'My Friends';
      renderUsers();
    });

    $('#tabDiscover').addEventListener('click', () => {
      currentTab = 'discover';
      $('#tabDiscover').classList.add('active');
      $('#tabMyFriends').classList.remove('active');
      $('#gridEyebrow').textContent = 'Explore';
      $('#gridTitle').textContent = 'Discover & Connect';
      renderUsers();
    });

    // --- MAIN NAVIGATION TABS (CONNECTIONS, FEED, CHATS) ---
    $('#tabBtnConnections').addEventListener('click', () => {
      currentMainTab = 'connections';
      $('#tabBtnConnections').classList.add('active');
      $('#tabBtnFeed').classList.remove('active');
      $('#tabBtnChats').classList.remove('active');
      $('#connectionsView').style.display = 'block';
      $('#feedView').style.display = 'none';
      $('#chatsView').style.display = 'none';
    });

    $('#tabBtnFeed').addEventListener('click', () => {
      currentMainTab = 'feed';
      $('#tabBtnFeed').classList.add('active');
      $('#tabBtnConnections').classList.remove('active');
      $('#tabBtnChats').classList.remove('active');
      $('#connectionsView').style.display = 'none';
      $('#feedView').style.display = 'block';
      $('#chatsView').style.display = 'none';
      loadPosts();
    });

    $('#tabBtnChats').addEventListener('click', () => {
      currentMainTab = 'chats';
      $('#tabBtnChats').classList.add('active');
      $('#tabBtnConnections').classList.remove('active');
      $('#tabBtnFeed').classList.remove('active');
      $('#connectionsView').style.display = 'none';
      $('#feedView').style.display = 'none';
      $('#chatsView').style.display = 'block';
      renderChatFriends();
    });

    $('#topbarChatBtn').addEventListener('click', () => {
      $('#tabBtnChats').click();
      $('#chatsView').scrollIntoView({ behavior: 'smooth' });
    });

    // --- MY PROFILE MODAL, BIO, PHOTO & PRIVACY ---
    $('#myProfileBtn').addEventListener('click', openMyProfileModal);

    function openMyProfileModal() {
      const auth = appState.auth || {};
      const profile = auth.profile || {};
      $('#myAvatar').innerHTML = renderAvatar(profile.avatar, auth.username, 78, profile.profile_photo);
      $('#myUsername').textContent = auth.username;
      $('#myRoleBadge').textContent = auth.role === 'admin' ? '👑 Administrator' : '💕 Normal User';
      $('#myBioDisplay').textContent = profile.bio ? `"${profile.bio}"` : 'No bio added yet. Add one below!';
      $('#myAgeDisplay').textContent = profile.age ? `${profile.age} years old` : 'Not set';
      $('#myCityDisplay').textContent = profile.city || 'Not set';

      const priv = profile.privacy || 'public';
      const privEl = $('#myPrivacyDisplay');
      privEl.textContent = priv === 'private' ? '🔒 Private Account' : '🌐 Public Account';
      privEl.className = 'privacy-badge ' + priv;

      const removePhotoBtn = $('#removePhotoBtn');
      if (removePhotoBtn) {
        removePhotoBtn.style.display = profile.profile_photo ? 'inline-block' : 'none';
      }

      $('#editBioInput').value = profile.bio || '';
      $('#editAgeInput').value = profile.age || '';
      $('#editCityInput').value = profile.city || '';
      if ($('#editPrivacySelect')) $('#editPrivacySelect').value = priv;

      $('#myProfileViewMode').style.display = 'block';
      $('#editProfileForm').style.display = 'none';
      $('#myProfileModal').classList.add('open');
    }

    $('#closeMyProfileModal').addEventListener('click', () => {
      $('#myProfileModal').classList.remove('open');
    });

    $('#uploadPhotoBtn').addEventListener('click', () => {
      $('#profilePhotoFileInput').click();
    });

    $('#profilePhotoFileInput').addEventListener('change', async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      try {
        showToast('Processing photo...');
        const base64 = await compressImage(file, 600, 0.75);
        const res = await request('/api/profile/photo', {
          method: 'POST',
          body: JSON.stringify({ photo: base64 })
        });
        showToast(res.message);
        e.target.value = '';
        await refresh();
        openMyProfileModal();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    $('#removePhotoBtn').addEventListener('click', async () => {
      if (!confirm('Remove profile photo and restore vector avatar?')) return;
      try {
        const res = await request('/api/profile/photo', { method: 'DELETE' });
        showToast(res.message);
        await refresh();
        openMyProfileModal();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    $('#togglePrivacyBtn').addEventListener('click', async () => {
      try {
        const current = (appState.auth && appState.auth.profile && appState.auth.profile.privacy) || 'public';
        const newPrivacy = current === 'private' ? 'public' : 'private';
        const res = await request('/api/profile/privacy', {
          method: 'POST',
          body: JSON.stringify({ privacy: newPrivacy })
        });
        showToast(res.message);
        await refresh();
        openMyProfileModal();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    $('#startEditProfileBtn').addEventListener('click', () => {
      $('#myProfileViewMode').style.display = 'none';
      $('#editProfileForm').style.display = 'block';
    });

    $('#cancelEditProfileBtn').addEventListener('click', () => {
      $('#myProfileViewMode').style.display = 'block';
      $('#editProfileForm').style.display = 'none';
    });

    $('#editProfileForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const data = Object.fromEntries(new FormData(e.target));
        const res = await request('/api/profile', { method: 'POST', body: JSON.stringify(data) });
        if (data.privacy) {
          await request('/api/profile/privacy', { method: 'POST', body: JSON.stringify({ privacy: data.privacy }) });
        }
        showToast(res.message);
        $('#myProfileModal').classList.remove('open');
        await refresh();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // --- STORIES FEATURE (24-Hour Expiring Stories) ---
    async function loadStories() {
      if (!appState.auth || !appState.auth.is_authenticated) return;
      try {
        const data = await request('/api/stories');
        cachedStories = data.stories || [];
        renderStoriesTray();
      } catch (e) {}
    }

    function renderStoriesTray() {
      const auth = appState.auth || {};
      const currentUser = auth.username;
      const myProfile = auth.profile || {};

      $('#myStoryAvatarSlot').innerHTML = renderAvatar(myProfile.avatar, currentUser, 58, myProfile.profile_photo);
      const myGroup = cachedStories.find(g => g.author === currentUser);
      const myCount = (myGroup && myGroup.items) ? myGroup.items.length : 0;
      const myRing = $('#myStoryRing');
      if (myCount > 0) {
        myRing.className = 'story-ring unseen';
      } else {
        myRing.className = 'story-ring empty-mine';
      }

      const otherGroups = cachedStories.filter(g => g.author !== currentUser && g.items && g.items.length > 0);
      const container = $('#storiesListContainer');
      if (!otherGroups.length) {
        container.innerHTML = '';
        return;
      }

      container.innerHTML = otherGroups.map(g => `
        <div class="story-item" data-view-story="${escapeAttr(g.author)}">
          <div class="story-ring unseen">
            <div class="story-inner">${renderAvatar(g.author_avatar, g.author, 58, g.author_photo)}</div>
          </div>
          <span class="story-label">${escapeHtml(g.author)}</span>
        </div>
      `).join('');
    }

    $('#openAddStoryBtn').addEventListener('click', () => openCreateStoryModal());
    $('#addStoryCircle').addEventListener('click', (e) => {
      const currentUser = (appState.auth && appState.auth.username) || '';
      const myGroup = cachedStories.find(g => g.author === currentUser);
      if (myGroup && myGroup.items && myGroup.items.length > 0 && !e.target.closest('.story-plus-badge')) {
        openStoryViewer(currentUser);
      } else {
        openCreateStoryModal();
      }
    });

    document.addEventListener('click', (e) => {
      const storyCircle = e.target.closest('[data-view-story]');
      if (storyCircle) {
        const author = storyCircle.dataset.viewStory;
        openStoryViewer(author);
      }
    });

    // --- WEB AUDIO SYNTHESIZER ENGINE (Realistic, Instant Melodic Loops) ---
    const SynthEngine = (() => {
      let ctx = null;
      let activeNodes = [];
      let isPlaying = false;
      let currentTimer = null;

      function getContext() {
        if (!ctx) {
          const AudioContextClass = window.AudioContext || window.webkitAudioContext;
          if (AudioContextClass) ctx = new AudioContextClass();
        }
        if (ctx && ctx.state === 'suspended') ctx.resume();
        return ctx;
      }

      function stop() {
        isPlaying = false;
        if (currentTimer) {
          clearTimeout(currentTimer);
          currentTimer = null;
        }
        activeNodes.forEach(node => {
          try { node.stop(); } catch(e){}
          try { node.disconnect(); } catch(e){}
        });
        activeNodes = [];
      }

      function playTone(freq, startTime, duration, type = 'sine', gainVal = 0.12) {
        const c = getContext();
        if (!c || isStoryMuted) return;
        try {
          const osc = c.createOscillator();
          const gain = c.createGain();
          osc.type = type;
          osc.frequency.setValueAtTime(freq, startTime);

          gain.gain.setValueAtTime(0.001, startTime);
          gain.gain.exponentialRampToValueAtTime(gainVal, startTime + 0.04);
          gain.gain.exponentialRampToValueAtTime(0.0001, startTime + duration);

          osc.connect(gain);
          gain.connect(c.destination);

          osc.start(startTime);
          osc.stop(startTime + duration + 0.05);
          activeNodes.push(osc);
        } catch(e) {}
      }

      function playChord(freqs, startTime, duration, type = 'triangle', gainVal = 0.07) {
        freqs.forEach(f => playTone(f, startTime, duration, type, gainVal));
      }

      const N = {
        C3: 130.81, D3: 146.83, E3: 164.81, F3: 174.61, G3: 196.00, A3: 220.00, B3: 246.94,
        C4: 261.63, D4: 293.66, E4: 329.63, F4: 349.23, G4: 392.00, A4: 440.00, B4: 493.88,
        C5: 523.25, D5: 587.33, E5: 659.25, F5: 698.46, G5: 783.99, A5: 880.00, B5: 987.77
      };

      function playPreset(preset) {
        stop();
        if (isStoryMuted) return;
        const c = getContext();
        if (!c) return;
        isPlaying = true;
        const t0 = c.currentTime + 0.04;

        function loop(offset) {
          if (!isPlaying || isStoryMuted) return;
          if (preset === 'pop_upbeat') {
            const chords = [
              { bass: N.C3, chord: [N.C4, N.E4, N.G4], arp: [N.C5, N.G4, N.E4, N.G4] },
              { bass: N.G3, chord: [N.B3, N.D4, N.G4], arp: [N.D5, N.B4, N.G4, N.B4] },
              { bass: N.A3, chord: [N.C4, N.E4, N.A4], arp: [N.E5, N.C5, N.A4, N.C5] },
              { bass: N.F3, chord: [N.A3, N.C4, N.F4], arp: [N.F5, N.C5, N.A4, N.C5] }
            ];
            chords.forEach((bar, idx) => {
              const bt = offset + idx * 1.4;
              playTone(bar.bass, bt, 1.2, 'sawtooth', 0.1);
              playChord(bar.chord, bt, 0.6, 'triangle', 0.06);
              playChord(bar.chord, bt + 0.7, 0.6, 'triangle', 0.06);
              bar.arp.forEach((note, nIdx) => {
                playTone(note, bt + nIdx * 0.35, 0.3, 'sine', 0.08);
              });
            });
            currentTimer = setTimeout(() => loop(c.currentTime + 0.08), 5600);
          } else if (preset === 'romantic_piano') {
            const prog = [
              [N.F3, [N.A3, N.C4, N.F4], [N.C5, N.A4, N.F4, N.A4]],
              [N.C3, [N.G3, N.C4, N.E4], [N.G4, N.E4, N.C4, N.E4]],
              [N.D3, [N.F3, N.A3, N.D4], [N.F5, N.D5, N.A4, N.D5]],
              [N.B3, [N.D4, N.F4, N.B4], [N.D5, N.B4, N.F4, N.B4]]
            ];
            prog.forEach((bar, idx) => {
              const bt = offset + idx * 1.6;
              playTone(bar[0], bt, 1.4, 'sine', 0.12);
              playChord(bar[1], bt, 1.3, 'sine', 0.08);
              bar[2].forEach((note, nIdx) => {
                playTone(note, bt + nIdx * 0.4, 0.35, 'triangle', 0.07);
              });
            });
            currentTimer = setTimeout(() => loop(c.currentTime + 0.08), 6400);
          } else if (preset === 'bollywood_beat') {
            const notes = [N.D4, N.F4, N.G4, N.A4, N.C5, N.D5, N.C5, N.A4];
            notes.forEach((nt, idx) => {
              playTone(nt, offset + idx * 0.32, 0.28, 'sine', 0.1);
              if (idx % 2 === 0) playTone(N.D3, offset + idx * 0.32, 0.3, 'triangle', 0.14);
            });
            currentTimer = setTimeout(() => loop(c.currentTime + 0.08), 2600);
          } else if (preset === 'chill_lofi') {
            const chords = [
              [N.D3, [N.F3, N.A3, N.C4, N.E4]],
              [N.G3, [N.F3, N.B3, N.D4]],
              [N.C3, [N.E3, N.G3, N.B3, N.D4]]
            ];
            chords.forEach((ch, idx) => {
              const bt = offset + idx * 1.8;
              playTone(ch[0], bt, 1.6, 'sine', 0.12);
              playChord(ch[1], bt, 1.6, 'triangle', 0.07);
              playTone(N.E5, bt + 0.45, 0.5, 'sine', 0.05);
              playTone(N.C5, bt + 1.1, 0.5, 'sine', 0.05);
            });
            currentTimer = setTimeout(() => loop(c.currentTime + 0.08), 5400);
          } else {
            const scale = [N.C4, N.E4, N.G4, N.B4, N.C5];
            scale.forEach((nt, idx) => playTone(nt, offset + idx * 0.45, 0.4, 'sine', 0.09));
            currentTimer = setTimeout(() => loop(c.currentTime + 0.08), 2400);
          }
        }
        loop(t0);
      }

      return {
        play: playPreset,
        stop: stop,
        isPlaying: () => isPlaying
      };
    })();

    // --- INSTAGRAM-STYLE MUSIC PLAYLIST LIBRARY ---
    const INSTA_MUSIC_LIBRARY = [
      // 🔥 For You / Trending Hits
      {
        id: "trend_1",
        title: "Espresso",
        artist: "Sabrina Carpenter",
        category: "trending",
        album: "Short n' Sweet",
        cover: "linear-gradient(135deg, #f59e0b, #ec4899)",
        icon: "☕",
        duration: "0:30",
        synth_track: "pop_upbeat"
      },
      {
        id: "trend_2",
        title: "Die With A Smile",
        artist: "Lady Gaga & Bruno Mars",
        category: "trending",
        album: "Single",
        cover: "linear-gradient(135deg, #3b82f6, #ec4899)",
        icon: "💙",
        duration: "0:30",
        synth_track: "romantic_piano"
      },
      {
        id: "trend_3",
        title: "Starboy",
        artist: "The Weeknd ft. Daft Punk",
        category: "trending",
        album: "Starboy",
        cover: "linear-gradient(135deg, #ef4444, #18181b)",
        icon: "⚡",
        duration: "0:30",
        synth_track: "pop_upbeat"
      },
      {
        id: "trend_4",
        title: "Birds of a Feather",
        artist: "Billie Eilish",
        category: "trending",
        album: "Hit Me Hard and Soft",
        cover: "linear-gradient(135deg, #06b6d4, #3b82f6)",
        icon: "🪶",
        duration: "0:30",
        synth_track: "chill_lofi"
      },
      {
        id: "trend_5",
        title: "Blinding Lights",
        artist: "The Weeknd",
        category: "trending",
        album: "After Hours",
        cover: "linear-gradient(135deg, #dc2626, #7c3aed)",
        icon: "🏎️",
        duration: "0:30",
        synth_track: "pop_upbeat"
      },

      // 💖 Romance / Love
      {
        id: "love_1",
        title: "Until I Found You",
        artist: "Stephen Sanchez",
        category: "love",
        album: "Easy On My Eyes",
        cover: "linear-gradient(135deg, #f472b6, #fda4af)",
        icon: "💌",
        duration: "0:30",
        synth_track: "romantic_piano"
      },
      {
        id: "love_2",
        title: "Lover",
        artist: "Taylor Swift",
        category: "love",
        album: "Lover",
        cover: "linear-gradient(135deg, #fb7185, #c084fc)",
        icon: "💖",
        duration: "0:30",
        synth_track: "romantic_piano"
      },
      {
        id: "love_3",
        title: "Kesariya",
        artist: "Arijit Singh & Pritam",
        category: "love",
        album: "Brahmāstra",
        cover: "linear-gradient(135deg, #f97316, #e11d48)",
        icon: "🧡",
        duration: "0:30",
        synth_track: "bollywood_beat"
      },
      {
        id: "love_4",
        title: "Golden Hour",
        artist: "JVKE",
        category: "love",
        album: "this is what feels like",
        cover: "linear-gradient(135deg, #eab308, #f43f5e)",
        icon: "✨",
        duration: "0:30",
        synth_track: "romantic_piano"
      },
      {
        id: "love_5",
        title: "Perfect",
        artist: "Ed Sheeran",
        category: "love",
        album: "÷ (Divide)",
        cover: "linear-gradient(135deg, #0284c7, #38bdf8)",
        icon: "💍",
        duration: "0:30",
        synth_track: "romantic_piano"
      },
      {
        id: "love_6",
        title: "Dandelions",
        artist: "Ruth B.",
        category: "love",
        album: "Safe Haven",
        cover: "linear-gradient(135deg, #a855f7, #ec4899)",
        icon: "🌼",
        duration: "0:30",
        synth_track: "romantic_piano"
      },

      // 🇮🇳 Bollywood & Desi Viral
      {
        id: "bolly_1",
        title: "Tauba Tauba",
        artist: "Karan Aujla",
        category: "bollywood",
        album: "Bad Newz",
        cover: "linear-gradient(135deg, #84cc16, #065f46)",
        icon: "🕺",
        duration: "0:30",
        synth_track: "bollywood_beat"
      },
      {
        id: "bolly_2",
        title: "Satranga",
        artist: "Arijit Singh & Shreyas Puranik",
        category: "bollywood",
        album: "Animal",
        cover: "linear-gradient(135deg, #b91c1c, #450a0a)",
        icon: "🌹",
        duration: "0:30",
        synth_track: "bollywood_beat"
      },
      {
        id: "bolly_3",
        title: "Chaleya",
        artist: "Arijit Singh & Shilpa Rao",
        category: "bollywood",
        album: "Jawan",
        cover: "linear-gradient(135deg, #0284c7, #6366f1)",
        icon: "💫",
        duration: "0:30",
        synth_track: "bollywood_beat"
      },
      {
        id: "bolly_4",
        title: "Apna Bana Le",
        artist: "Arijit Singh & Sachin-Jigar",
        category: "bollywood",
        album: "Bhediya",
        cover: "linear-gradient(135deg, #ea580c, #7c2d12)",
        icon: "🌙",
        duration: "0:30",
        synth_track: "bollywood_beat"
      },
      {
        id: "bolly_5",
        title: "Maan Meri Jaan",
        artist: "King",
        category: "bollywood",
        album: "Champagne Talk",
        cover: "linear-gradient(135deg, #d97706, #92400e)",
        icon: "👑",
        duration: "0:30",
        synth_track: "bollywood_beat"
      },

      // 🎧 Pop & Beats
      {
        id: "pop_1",
        title: "Levitating",
        artist: "Dua Lipa",
        category: "pop",
        album: "Future Nostalgia",
        cover: "linear-gradient(135deg, #8b5cf6, #ec4899)",
        icon: "🪩",
        duration: "0:30",
        synth_track: "pop_upbeat"
      },
      {
        id: "pop_2",
        title: "As It Was",
        artist: "Harry Styles",
        category: "pop",
        album: "Harry's House",
        cover: "linear-gradient(135deg, #f43f5e, #3b82f6)",
        icon: "🏠",
        duration: "0:30",
        synth_track: "pop_upbeat"
      },

      // 🌙 Lo-Fi & Chill
      {
        id: "lofi_1",
        title: "Midnight Coffee",
        artist: "Lo-Fi Dreams",
        category: "lofi",
        album: "Late Night Beats",
        cover: "linear-gradient(135deg, #6366f1, #1e1b4b)",
        icon: "☕",
        duration: "0:30",
        synth_track: "chill_lofi"
      },
      {
        id: "lofi_2",
        title: "Sunset Boulevard",
        artist: "Neon Skyline",
        category: "lofi",
        album: "Synthwave Memories",
        cover: "linear-gradient(135deg, #ec4899, #4338ca)",
        icon: "🌆",
        duration: "0:30",
        synth_track: "chill_lofi"
      }
    ];

    let currentMusicCategory = 'trending';
    let currentMusicSearch = '';
    let customAudioDataUrl = '';

    // --- MUSIC PICKER FUNCTIONS ---
    function openMusicPickerModal() {
      currentMusicCategory = 'trending';
      currentMusicSearch = '';
      $('#musicSearchInput').value = '';
      $('#musicSearchClear').style.display = 'none';
      stopMusicPreview();

      // Set active category pill
      document.querySelectorAll('#musicCatTray .music-cat-pill').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.cat === 'trending');
      });

      renderMusicPlaylist();
      $('#musicPickerModal').classList.add('open');
    }

    function closeMusicPickerModal() {
      stopMusicPreview();
      $('#musicPickerModal').classList.remove('open');
    }

    $('#closeMusicPickerModal').addEventListener('click', closeMusicPickerModal);
    $('#openMusicPickerBtn').addEventListener('click', openMusicPickerModal);

    function stopMusicPreview() {
      currentPreviewSongId = null;
      SynthEngine.stop();
      previewAudioElement.pause();
      previewAudioElement.currentTime = 0;
      updatePreviewPlayButtons();
    }

    function renderMusicPlaylist() {
      if (currentMusicCategory === 'custom') {
        $('#musicPlaylistList').style.display = 'none';
        $('#customMusicUploadPanel').style.display = 'block';
        return;
      }
      $('#customMusicUploadPanel').style.display = 'none';
      $('#musicPlaylistList').style.display = 'block';

      const q = currentMusicSearch.toLowerCase().trim();
      const filtered = INSTA_MUSIC_LIBRARY.filter(song => {
        const matchesCat = (currentMusicCategory === 'trending') || (song.category === currentMusicCategory);
        const matchesQuery = !q || song.title.toLowerCase().includes(q) || song.artist.toLowerCase().includes(q);
        return matchesCat && matchesQuery;
      });

      const container = $('#musicPlaylistList');
      if (!filtered.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:40px 20px;color:#9ca3af">
            <span style="font-size:32px">🔍</span>
            <p style="margin:8px 0 0;font-size:13px">No songs found matching "${escapeHtml(q)}".</p>
            <button type="button" class="mini-btn" id="suggestCustomBtn" style="margin-top:10px;background:#ec4899;color:#fff;border:none">Upload Custom Song</button>
          </div>
        `;
        const scBtn = $('#suggestCustomBtn');
        if (scBtn) {
          scBtn.addEventListener('click', () => {
            currentMusicCategory = 'custom';
            document.querySelectorAll('#musicCatTray .music-cat-pill').forEach(b => {
              b.classList.toggle('active', b.dataset.cat === 'custom');
            });
            renderMusicPlaylist();
          });
        }
        return;
      }

      container.innerHTML = filtered.map(song => {
        const isPlaying = currentPreviewSongId === song.id;
        return `
          <div class="music-row-item" data-song-id="${escapeAttr(song.id)}">
            <div class="music-row-left">
              <div class="music-row-art" style="background:${escapeAttr(song.cover)}">
                ${song.icon || '🎵'}
              </div>
              <div class="music-row-details">
                <div class="music-row-title">${escapeHtml(song.title)}</div>
                <div class="music-row-artist">${escapeHtml(song.artist)} • ${escapeHtml(song.duration)}</div>
              </div>
            </div>
            <div class="music-row-actions">
              <button type="button" class="music-preview-btn ${isPlaying ? 'playing' : ''}" data-preview-id="${escapeAttr(song.id)}" title="Preview">
                ${isPlaying ?
                  '<div class="mini-equalizer-bars"><span></span><span></span><span></span><span></span></div>' :
                  '▶'
                }
              </button>
            </div>
          </div>
        `;
      }).join('');
    }

    function updatePreviewPlayButtons() {
      document.querySelectorAll('.music-preview-btn').forEach(btn => {
        const id = btn.dataset.previewId;
        const isPlaying = currentPreviewSongId === id;
        btn.classList.toggle('playing', isPlaying);
        btn.innerHTML = isPlaying ?
          '<div class="mini-equalizer-bars"><span></span><span></span><span></span><span></span></div>' :
          '▶';
      });
    }

    // Category tray clicks
    $('#musicCatTray').addEventListener('click', (e) => {
      const pill = e.target.closest('.music-cat-pill');
      if (!pill) return;
      document.querySelectorAll('#musicCatTray .music-cat-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      currentMusicCategory = pill.dataset.cat;
      stopMusicPreview();
      renderMusicPlaylist();
    });

    // Search input
    $('#musicSearchInput').addEventListener('input', (e) => {
      currentMusicSearch = e.target.value;
      $('#musicSearchClear').style.display = currentMusicSearch ? 'inline' : 'none';
      renderMusicPlaylist();
    });

    $('#musicSearchClear').addEventListener('click', () => {
      $('#musicSearchInput').value = '';
      currentMusicSearch = '';
      $('#musicSearchClear').style.display = 'none';
      renderMusicPlaylist();
    });

    // Preview or Select from playlist
    $('#musicPlaylistList').addEventListener('click', (e) => {
      const previewBtn = e.target.closest('.music-preview-btn');
      if (previewBtn) {
        e.stopPropagation();
        const id = previewBtn.dataset.previewId;
        if (currentPreviewSongId === id) {
          stopMusicPreview();
        } else {
          stopMusicPreview();
          const song = INSTA_MUSIC_LIBRARY.find(s => s.id === id);
          if (song) {
            currentPreviewSongId = id;
            updatePreviewPlayButtons();
            if (song.audio_url) {
              previewAudioElement.src = song.audio_url;
              previewAudioElement.play().catch(e => console.log(e));
            } else if (song.synth_track) {
              SynthEngine.play(song.synth_track);
            }
          }
        }
        return;
      }

      const row = e.target.closest('.music-row-item');
      if (row) {
        const id = row.dataset.songId;
        const song = INSTA_MUSIC_LIBRARY.find(s => s.id === id);
        if (song) {
          selectSongForStory(song);
        }
      }
    });

    // Custom song file upload & URL handlers
    $('#triggerAudioFileBtn').addEventListener('click', () => {
      $('#customAudioFileInput').click();
    });

    $('#customAudioFileInput').addEventListener('change', (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      if (file.size > 20 * 1024 * 1024) {
        showToast('Please choose an audio file under 20MB.', true);
        return;
      }
      showToast('Loading audio file...');
      const reader = new FileReader();
      reader.onload = (re) => {
        customAudioDataUrl = re.target.result;
        const cleanName = file.name.replace(/\.[^/.]+$/, "").replace(/[-_]/g, ' ');
        if (!$('#customSongTitleInput').value) {
          $('#customSongTitleInput').value = cleanName;
        }
        if (!$('#customSongArtistInput').value) {
          $('#customSongArtistInput').value = 'My Sound';
        }
        showToast('Audio file loaded! Click Apply to attach.');
      };
      reader.readAsDataURL(file);
    });

    $('#useCustomSongBtn').addEventListener('click', () => {
      const audioUrl = customAudioDataUrl || $('#customAudioUrlInput').value.trim();
      const title = $('#customSongTitleInput').value.trim() || 'Custom Track';
      const artist = $('#customSongArtistInput').value.trim() || 'My Music';

      if (!audioUrl) {
        showToast('Please upload an audio file or enter an audio URL.', true);
        return;
      }

      const customSong = {
        id: 'custom_' + Date.now(),
        title: title,
        artist: artist,
        category: 'custom',
        album: 'My Playlist',
        cover: 'linear-gradient(135deg, #ec4899, #8b5cf6)',
        icon: '🎵',
        audio_url: audioUrl,
        duration: '0:30'
      };

      selectSongForStory(customSong);
    });

    function selectSongForStory(song) {
      stopMusicPreview();
      selectedStorySong = song;

      $('#storyMusicTriggerWrap').style.display = 'none';
      $('#attachedMusicCard').style.display = 'flex';
      $('#attachedSongTitle').textContent = song.title;
      $('#attachedSongArtist').textContent = song.artist;
      $('#attachedSongArt').style.background = song.cover || 'linear-gradient(135deg,#ec4899,#8b5cf6)';
      $('#attachedSongArt').innerHTML = song.icon || '🎵';

      closeMusicPickerModal();
      showToast(`Attached "🎵 ${song.title}" to your story!`);
    }

    // Attached music card preview / change / remove
    let attachedPreviewPlaying = false;
    $('#attachedPreviewBtn').addEventListener('click', () => {
      if (!selectedStorySong) return;
      if (attachedPreviewPlaying) {
        attachedPreviewPlaying = false;
        $('#attachedPreviewBtn').textContent = '▶';
        SynthEngine.stop();
        previewAudioElement.pause();
      } else {
        attachedPreviewPlaying = true;
        $('#attachedPreviewBtn').textContent = '⏸';
        if (selectedStorySong.audio_url) {
          previewAudioElement.src = selectedStorySong.audio_url;
          previewAudioElement.play().catch(e => console.log(e));
        } else if (selectedStorySong.synth_track) {
          SynthEngine.play(selectedStorySong.synth_track);
        }
      }
    });

    $('#attachedChangeBtn').addEventListener('click', openMusicPickerModal);

    $('#attachedRemoveBtn').addEventListener('click', () => {
      attachedPreviewPlaying = false;
      $('#attachedPreviewBtn').textContent = '▶';
      SynthEngine.stop();
      previewAudioElement.pause();
      selectedStorySong = null;
      $('#attachedMusicCard').style.display = 'none';
      $('#storyMusicTriggerWrap').style.display = 'block';
    });

    // Sticker style pills click in Create Story modal
    document.querySelectorAll('.sticker-opt-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        document.querySelectorAll('.sticker-opt-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        selectedStickerStyle = pill.dataset.sticker || 'card';
      });
    });

    // --- CREATE STORY MODAL ---
    $('#openAddStoryBtn').addEventListener('click', () => openCreateStoryModal());
    $('#addStoryCircle').addEventListener('click', (e) => {
      const currentUser = (appState.auth && appState.auth.username) || '';
      const myGroup = cachedStories.find(g => g.author === currentUser);
      if (myGroup && myGroup.items && myGroup.items.length > 0 && !e.target.closest('.story-plus-badge')) {
        openStoryViewer(currentUser);
      } else {
        openCreateStoryModal();
      }
    });

    document.addEventListener('click', (e) => {
      const storyCircle = e.target.closest('[data-view-story]');
      if (storyCircle) {
        const author = storyCircle.dataset.viewStory;
        openStoryViewer(author);
      }
    });

    function openCreateStoryModal() {
      selectedStoryMediaBase64 = null;
      selectedStoryMediaType = 'image';
      selectedStorySong = null;
      selectedStickerStyle = 'card';
      customAudioDataUrl = '';
      attachedPreviewPlaying = false;
      $('#attachedPreviewBtn').textContent = '▶';

      $('#storyPreviewImg').style.display = 'none';
      $('#storyPreviewVideo').style.display = 'none';
      $('#storyPreviewVideo').pause();
      $('#storyMediaTypeBadge').style.display = 'none';
      $('#storyUploadPrompt').style.display = 'block';
      $('#storyCaptionInput').value = '';

      $('#attachedMusicCard').style.display = 'none';
      $('#storyMusicTriggerWrap').style.display = 'block';
      document.querySelectorAll('.sticker-opt-pill').forEach(p => {
        p.classList.toggle('active', p.dataset.sticker === 'card');
      });

      $('#createStoryModal').classList.add('open');
    }

    $('#closeCreateStoryModal').addEventListener('click', () => {
      SynthEngine.stop();
      previewAudioElement.pause();
      $('#storyPreviewVideo').pause();
      $('#createStoryModal').classList.remove('open');
    });

    $('#cancelStoryBtn').addEventListener('click', () => {
      SynthEngine.stop();
      previewAudioElement.pause();
      $('#storyPreviewVideo').pause();
      $('#createStoryModal').classList.remove('open');
    });

    $('#storyImagePreviewBox').addEventListener('click', () => {
      $('#storyFileInput').click();
    });

    $('#storyFileInput').addEventListener('change', async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;

      if (file.type.startsWith('video/')) {
        if (file.size > 30 * 1024 * 1024) {
          showToast('Please select a video clip under 30MB.', true);
          return;
        }
        showToast('Loading story video clip...');
        const reader = new FileReader();
        reader.onload = (re) => {
          selectedStoryMediaBase64 = re.target.result;
          selectedStoryMediaType = 'video';
          $('#storyPreviewVideo').src = selectedStoryMediaBase64;
          $('#storyPreviewVideo').style.display = 'block';
          $('#storyPreviewVideo').play().catch(e => console.log(e));
          $('#storyPreviewImg').style.display = 'none';
          $('#storyUploadPrompt').style.display = 'none';
          $('#storyMediaTypeBadge').textContent = '🎬 Video Clip';
          $('#storyMediaTypeBadge').style.display = 'block';
        };
        reader.readAsDataURL(file);
      } else {
        try {
          showToast('Optimizing photo for story...');
          selectedStoryMediaBase64 = await compressImage(file, 900, 0.8);
          selectedStoryMediaType = 'image';
          $('#storyPreviewImg').src = selectedStoryMediaBase64;
          $('#storyPreviewImg').style.display = 'block';
          $('#storyPreviewVideo').style.display = 'none';
          $('#storyPreviewVideo').pause();
          $('#storyUploadPrompt').style.display = 'none';
          $('#storyMediaTypeBadge').textContent = '📸 Photo';
          $('#storyMediaTypeBadge').style.display = 'block';
        } catch (err) {
          showToast(err.message, true);
        }
      }
    });

    $('#publishStoryBtn').addEventListener('click', async () => {
      if (!selectedStoryMediaBase64) {
        showToast('Please pick a photo or video for your story!', true);
        return;
      }
      try {
        const caption = $('#storyCaptionInput').value.trim();
        const payload = {
          media: selectedStoryMediaBase64,
          media_type: selectedStoryMediaType,
          caption: caption,
          song: selectedStorySong ? {
            title: selectedStorySong.title,
            artist: selectedStorySong.artist,
            album: selectedStorySong.album || '',
            cover: selectedStorySong.cover || '',
            icon: selectedStorySong.icon || '🎵',
            audio_url: selectedStorySong.audio_url || '',
            synth_track: selectedStorySong.synth_track || '',
            sticker_style: selectedStickerStyle
          } : null
        };

        const res = await request('/api/stories', {
          method: 'POST',
          body: JSON.stringify(payload)
        });

        showToast(res.message);
        SynthEngine.stop();
        previewAudioElement.pause();
        $('#storyPreviewVideo').pause();
        $('#createStoryModal').classList.remove('open');
        await loadStories();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // --- INSTAGRAM-STYLE STORY VIEWER ---
    function openStoryViewer(author) {
      const group = cachedStories.find(g => g.author === author);
      if (!group || !group.items || !group.items.length) {
        showToast('No active stories for this profile.', true);
        return;
      }
      currentViewingStories = group.items;
      currentStoryIndex = 0;
      $('#storyViewerModal').classList.add('open');
      showStoryAt(currentStoryIndex);
    }

    function showStoryAt(index) {
      if (index >= currentViewingStories.length) {
        closeStoryViewerModal();
        return;
      }
      if (index < 0) {
        currentStoryIndex = 0;
        index = 0;
      }
      const s = currentViewingStories[index];
      const auth = appState.auth || {};
      const isAdmin = auth.role === 'admin';
      const currentUser = auth.username;

      // Reset audio & synthesizer
      viewerAudioElement.pause();
      viewerAudioElement.currentTime = 0;
      SynthEngine.stop();

      const uObj = appState.users.find(u => u.username === s.author) || {};
      $('#storyViewerAvatar').innerHTML = renderAvatar(uObj.avatar, s.author, 36, uObj.profile_photo);
      $('#storyViewerUsername').textContent = s.author;
      $('#storyViewerTime').textContent = s.time_str || 'Recent';

      // Media Rendering (Image vs Video)
      const mediaVal = s.media || s.photo || s.image || '';
      const isVideo = s.media_type === 'video' || mediaVal.startsWith('data:video/');

      const imgEl = $('#storyViewerImage');
      const vidEl = $('#storyViewerVideo');

      if (isVideo) {
        imgEl.style.display = 'none';
        vidEl.style.display = 'block';
        vidEl.src = mediaVal;
        vidEl.currentTime = 0;
        vidEl.muted = isStoryMuted || !!s.song;
        vidEl.play().catch(e => console.log('Video autoplay:', e));
      } else {
        vidEl.style.display = 'none';
        vidEl.pause();
        imgEl.style.display = 'block';
        imgEl.src = mediaVal;
      }

      // Instagram Song Rendering
      const musicBadge = $('#storyViewerMusicBadge');
      const musicText = $('#storyViewerMusicText');
      const musicSticker = $('#storyViewerMusicSticker');

      if (s.song) {
        musicBadge.style.display = 'inline-flex';
        musicText.textContent = `${s.song.title} • ${s.song.artist}`;

        // Play song audio
        if (s.song.audio_url) {
          viewerAudioElement.src = s.song.audio_url;
          viewerAudioElement.muted = isStoryMuted;
          viewerAudioElement.currentTime = 0;
          viewerAudioElement.play().catch(e => console.log('Audio error:', e));
        } else if (s.song.synth_track) {
          if (!isStoryMuted) SynthEngine.play(s.song.synth_track);
        }

        // Render Instagram music sticker
        const style = s.song.sticker_style || 'card';
        if (style === 'pill') {
          musicSticker.className = 'story-insta-sticker sticker-style-pill';
          musicSticker.innerHTML = `
            <span>🎵</span>
            <strong>${escapeHtml(s.song.title)}</strong>
            <span style="opacity:0.75">• ${escapeHtml(s.song.artist)}</span>
            <div class="mini-equalizer-bars" style="margin-left:4px">
              <span></span><span></span><span></span>
            </div>
          `;
        } else if (style === 'vinyl') {
          musicSticker.className = 'story-insta-sticker sticker-style-vinyl';
          musicSticker.innerHTML = `
            <div class="insta-vinyl-disc ${isStoryMuted ? 'paused' : ''}">
              <div class="insta-vinyl-center" style="background:${escapeAttr(s.song.cover || '#ec4899')}">
                ${s.song.icon || '🎵'}
              </div>
            </div>
            <div class="insta-vinyl-label">🎵 ${escapeHtml(s.song.title)}</div>
          `;
        } else {
          // Default: Instagram Glass Card
          musicSticker.className = 'story-insta-sticker sticker-style-card';
          musicSticker.innerHTML = `
            <div class="sticker-thumb" style="background:${escapeAttr(s.song.cover || 'linear-gradient(135deg,#ec4899,#8b5cf6)')}">
              ${s.song.icon || '🎵'}
            </div>
            <div class="sticker-info">
              <div class="sticker-title">${escapeHtml(s.song.title)}</div>
              <div class="sticker-artist">${escapeHtml(s.song.artist)}</div>
            </div>
            <div class="mini-equalizer-bars" style="margin-left:6px">
              <span></span><span></span><span></span><span></span>
            </div>
          `;
        }
        musicSticker.style.display = 'flex';
      } else {
        musicBadge.style.display = 'none';
        musicSticker.style.display = 'none';
      }

      // Caption
      if (s.caption) {
        $('#storyViewerCaption').textContent = s.caption;
        $('#storyViewerCaptionBox').style.display = 'block';
      } else {
        $('#storyViewerCaptionBox').style.display = 'none';
      }

      // Close viewers modal if it was open on story change
      closeStoryViewersModal();

      // Record view if not my own story
      const isMyStory = (s.author === currentUser) || !!s.is_mine;
      if (currentUser && !isMyStory) {
        request('/api/stories/view', {
          method: 'POST',
          body: JSON.stringify({ story_id: s.id })
        }).then(res => {
          if (res && typeof res.views_count === 'number') {
            s.views_count = res.views_count;
          }
        }).catch(err => console.log('Story view record err:', err));
      }

      // Bottom bars: Chat/Like row vs Story Owner Activity row
      const chatRow = $('#storyViewerChatRow');
      const actRow = $('#storyViewerActivityRow');
      const storyInp = $('#storyReplyTextInput');
      const likeBtn = $('#storyLikeBtn');
      const heartIcon = $('#storyHeartIcon');
      const likeCountBadge = $('#storyLikeCount');

      if (isMyStory) {
        if (chatRow) chatRow.style.display = 'none';
        if (actRow) {
          actRow.style.display = 'flex';
          $('#storyActivityViewsCount').textContent = s.views_count || 0;
          $('#storyActivityLikesCount').textContent = s.likes_count || 0;
        }
      } else {
        if (actRow) actRow.style.display = 'none';
        if (chatRow) {
          chatRow.style.display = 'flex';
          if (storyInp) {
            storyInp.value = '';
            storyInp.placeholder = `Send message to ${s.author}...`;
          }
          if (likeBtn && heartIcon) {
            if (s.liked) {
              likeBtn.classList.add('liked');
              heartIcon.textContent = '❤️';
            } else {
              likeBtn.classList.remove('liked');
              heartIcon.textContent = '🤍';
            }
            if (likeCountBadge) {
              if (s.likes_count && s.likes_count > 0) {
                likeCountBadge.textContent = s.likes_count;
                likeCountBadge.style.display = 'block';
              } else {
                likeCountBadge.style.display = 'none';
              }
            }
          }
        }
      }

      // Delete button
      const delBtn = $('#deleteCurrentStoryBtn');
      if (s.author === currentUser || isAdmin) {
        delBtn.style.display = 'inline-block';
        delBtn.dataset.storyId = s.id;
      } else {
        delBtn.style.display = 'none';
      }

      // Duration: 10s if photo with song, video duration if video, 5s for photo
      let duration = 5000;
      if (isVideo) {
        duration = Math.max(5000, Math.min(25000, (vidEl.duration * 1000) || 12000));
      } else if (s.song) {
        duration = 10000;
      }
      storyTotalDuration = duration;
      startStoryTimer(duration);
    }

    function startStoryTimer(duration, initialElapsed = 0) {
      clearInterval(window.storyProgressTimer);
      const fill = $('#storyProgressFill');
      let elapsed = initialElapsed;
      const interval = 50;

      window.storyProgressTimer = setInterval(() => {
        if (isStoryPaused) return;
        elapsed += interval;
        const pct = Math.min(100, (elapsed / duration) * 100);
        fill.style.width = pct + '%';
        if (elapsed >= duration) {
          clearInterval(window.storyProgressTimer);
          currentStoryIndex++;
          showStoryAt(currentStoryIndex);
        }
      }, interval);
    }

    // Audio Mute/Unmute Toggle
    $('#storyAudioToggleBtn').addEventListener('click', (e) => {
      e.stopPropagation();
      isStoryMuted = !isStoryMuted;
      $('#storyAudioToggleBtn').textContent = isStoryMuted ? '🔇' : '🔊';

      viewerAudioElement.muted = isStoryMuted;
      const vidEl = $('#storyViewerVideo');
      const s = currentViewingStories[currentStoryIndex];
      if (vidEl) vidEl.muted = isStoryMuted || (s && !!s.song);

      const vinyl = document.querySelector('.insta-vinyl-disc');
      if (vinyl) vinyl.classList.toggle('paused', isStoryMuted);

      if (isStoryMuted) {
        SynthEngine.stop();
      } else if (s && s.song && s.song.synth_track) {
        SynthEngine.play(s.song.synth_track);
      }
    });

    // Tap Left for Previous / Tap Right for Next
    $('#storyTapLeft').addEventListener('click', (e) => {
      e.stopPropagation();
      if (currentStoryIndex > 0) {
        currentStoryIndex--;
        showStoryAt(currentStoryIndex);
      } else {
        showStoryAt(0);
      }
    });

    $('#storyTapRight').addEventListener('click', (e) => {
      e.stopPropagation();
      currentStoryIndex++;
      showStoryAt(currentStoryIndex);
    });

    // Hold/Press to Pause Story & Audio
    const viewerCard = $('#storyViewerCard');
    function pauseViewer(e) {
      if (e && e.target && (e.target.closest('#storyViewerChatRow') || e.target.closest('#storyViewerActivityRow') || e.target.closest('.story-heart-btn') || e.target.closest('#storyViewersModal'))) return;
      isStoryPaused = true;
      viewerAudioElement.pause();
      const vid = $('#storyViewerVideo');
      if (vid) vid.pause();
    }

    function resumeViewer() {
      if (isViewersModalOpen) return;
      if (!isStoryPaused) return;
      isStoryPaused = false;
      const s = currentViewingStories[currentStoryIndex];
      if (s && s.song && s.song.audio_url && !isStoryMuted) {
        viewerAudioElement.play().catch(e => console.log(e));
      }
      const vid = $('#storyViewerVideo');
      if (vid && s && (s.media_type === 'video' || (s.media && s.media.startsWith('data:video/')))) {
        vid.play().catch(e => console.log(e));
      }
    }

    viewerCard.addEventListener('mousedown', pauseViewer);
    viewerCard.addEventListener('mouseup', resumeViewer);
    viewerCard.addEventListener('touchstart', pauseViewer, { passive: true });
    viewerCard.addEventListener('touchend', resumeViewer, { passive: true });

    function closeStoryViewerModal() {
      closeStoryViewersModal();
      clearInterval(window.storyProgressTimer);
      isStoryPaused = false;
      viewerAudioElement.pause();
      viewerAudioElement.currentTime = 0;
      SynthEngine.stop();
      const vid = $('#storyViewerVideo');
      if (vid) {
        vid.pause();
        vid.src = '';
      }
      $('#storyViewerModal').classList.remove('open');
    }
    $('#closeStoryViewerModal').addEventListener('click', closeStoryViewerModal);

    // Floating hearts generator for Story Likes
    function spawnFloatingHearts(sourceElement, count = 6) {
      const container = $('#storyFloatingHeartsContainer');
      if (!container) return;
      const rect = sourceElement ? sourceElement.getBoundingClientRect() : null;
      const cardEl = $('#storyViewerCard');
      const cardRect = cardEl ? cardEl.getBoundingClientRect() : null;

      for (let i = 0; i < count; i++) {
        setTimeout(() => {
          const heart = document.createElement('div');
          heart.className = 'floating-story-heart';
          const heartsList = ['❤️', '💖', '💗', '💕', '✨'];
          heart.textContent = heartsList[Math.floor(Math.random() * heartsList.length)];

          const driftX = (Math.random() * 80 - 40);
          const rot = (Math.random() * 40 - 20);
          heart.style.setProperty('--drift-x', `${driftX}px`);
          heart.style.setProperty('--rot', `${rot}deg`);

          if (rect && cardRect) {
            const rightOffset = cardRect.right - rect.right + (rect.width / 2) - 12;
            heart.style.right = `${Math.max(16, rightOffset)}px`;
            heart.style.bottom = '24px';
          }

          container.appendChild(heart);
          setTimeout(() => heart.remove(), 1900);
        }, i * 75);
      }
    }

    // Story Like Action
    async function toggleStoryLike() {
      const s = currentViewingStories[currentStoryIndex];
      if (!s || !s.id) return;
      const likeBtn = $('#storyLikeBtn');
      const heartIcon = $('#storyHeartIcon');
      const likeCountBadge = $('#storyLikeCount');

      const wasLiked = !!s.liked;
      s.liked = !wasLiked;
      s.likes_count = Math.max(0, (s.likes_count || 0) + (s.liked ? 1 : -1));

      if (likeBtn && heartIcon) {
        if (s.liked) {
          likeBtn.classList.add('liked', 'pop-anim');
          heartIcon.textContent = '❤️';
          spawnFloatingHearts(likeBtn, 7);
          setTimeout(() => likeBtn.classList.remove('pop-anim'), 500);
        } else {
          likeBtn.classList.remove('liked');
          heartIcon.textContent = '🤍';
        }
        if (likeCountBadge) {
          if (s.likes_count > 0) {
            likeCountBadge.textContent = s.likes_count;
            likeCountBadge.style.display = 'block';
          } else {
            likeCountBadge.style.display = 'none';
          }
        }
      }

      try {
        const res = await request('/api/stories/like', {
          method: 'POST',
          body: JSON.stringify({ story_id: s.id })
        });
        s.liked = res.liked;
        s.likes_count = res.likes_count;
        if (typeof res.views_count === 'number') s.views_count = res.views_count;
        if (likeCountBadge) {
          if (s.likes_count > 0) {
            likeCountBadge.textContent = s.likes_count;
            likeCountBadge.style.display = 'block';
          } else {
            likeCountBadge.style.display = 'none';
          }
        }
      } catch (err) {
        s.liked = wasLiked;
        showToast(err.message || 'Could not like story', true);
      }
    }

    const storyLikeBtn = $('#storyLikeBtn');
    if (storyLikeBtn) {
      storyLikeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleStoryLike();
      });
    }

    // Double-click on story media container to like (Instagram gesture)
    const mediaContainer = $('#storyMediaContainer');
    if (mediaContainer) {
      mediaContainer.addEventListener('dblclick', (e) => {
        e.stopPropagation();
        const s = currentViewingStories[currentStoryIndex];
        const auth = appState.auth || {};
        if (s && s.author !== auth.username && !s.is_mine) {
          if (!s.liked) {
            toggleStoryLike();
          } else {
            spawnFloatingHearts($('#storyLikeBtn') || mediaContainer, 7);
          }
        }
      });
    }

    // Story Viewers Modal & Story Owner Activity Bar
    let isViewersModalOpen = false;

    async function openStoryViewersModal() {
      const s = currentViewingStories[currentStoryIndex];
      if (!s || !s.id) return;

      isViewersModalOpen = true;
      pauseViewer();

      const modal = $('#storyViewersModal');
      const listContainer = $('#storyViewersList');
      modal.classList.add('open');

      listContainer.innerHTML = '<div style="text-align:center;padding:30px 0;color:var(--text-muted, #94a3b8)">Loading viewers...</div>';

      try {
        const data = await request(`/api/stories/viewers?story_id=${encodeURIComponent(s.id)}`);
        const viewers = data.viewers || [];
        $('#viewersModalViewsBadge').textContent = `${data.views_count || viewers.length} views`;
        $('#viewersModalLikesBadge').textContent = `${data.likes_count || 0} likes`;

        $('#storyActivityViewsCount').textContent = data.views_count || viewers.length;
        $('#storyActivityLikesCount').textContent = data.likes_count || 0;
        s.views_count = data.views_count || viewers.length;
        s.likes_count = data.likes_count || 0;

        if (viewers.length === 0) {
          listContainer.innerHTML = `
            <div style="text-align:center;padding:40px 16px;color:var(--text-muted,#94a3b8)">
              <div style="font-size:36px;margin-bottom:8px">👁️</div>
              <strong style="color:#fff;display:block;font-size:14px;margin-bottom:4px">No views yet</strong>
              <small>When friends view your story, they will show up here.</small>
            </div>
          `;
          return;
        }

        listContainer.innerHTML = viewers.map(v => {
          const avatarHtml = renderAvatar(v.avatar, v.username, 38, v.profile_photo);
          return `
            <div class="viewer-item-row">
              <div class="viewer-user-info">
                <div style="width:38px;height:38px;border-radius:50%;overflow:hidden;flex-shrink:0">
                  ${avatarHtml}
                </div>
                <div class="viewer-names">
                  <strong>
                    ${escapeHtml(v.name || v.username)}
                    ${v.liked ? '<span class="viewer-liked-badge" title="Liked your story">❤️</span>' : ''}
                  </strong>
                  <small>@${escapeHtml(v.username)} ${v.time_str ? '• ' + escapeHtml(v.time_str) : ''}</small>
                </div>
              </div>
              <div class="viewer-item-actions">
                <button type="button" class="viewer-chat-btn" data-chat="${escapeAttr(v.username)}" title="Message ${escapeAttr(v.username)}">
                  💬 Chat
                </button>
              </div>
            </div>
          `;
        }).join('');
      } catch (err) {
        listContainer.innerHTML = `<div style="text-align:center;padding:20px;color:#ef4444">${escapeHtml(err.message || 'Failed to load viewers.')}</div>`;
      }
    }

    function closeStoryViewersModal() {
      const modal = $('#storyViewersModal');
      if (modal) modal.classList.remove('open');
      if (isViewersModalOpen) {
        isViewersModalOpen = false;
        resumeViewer();
      }
    }

    const activityRow = $('#storyViewerActivityRow');
    if (activityRow) {
      activityRow.addEventListener('click', (e) => {
        e.stopPropagation();
        openStoryViewersModal();
      });
    }

    const closeViewersModalBtn = $('#closeStoryViewersModal');
    if (closeViewersModalBtn) {
      closeViewersModalBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        closeStoryViewersModal();
      });
    }

    const viewersModal = $('#storyViewersModal');
    if (viewersModal) {
      viewersModal.addEventListener('click', (e) => {
        if (e.target === viewersModal) {
          closeStoryViewersModal();
        }
      });
    }

    function handleStoryReply() {
      const s = currentViewingStories[currentStoryIndex];
      if (!s || !s.author) return;
      const input = $('#storyReplyTextInput');
      const text = input ? input.value.trim() : '';
      const author = s.author;
      closeStoryViewerModal();
      openChatWith(author);
      if (text) {
        setTimeout(() => {
          const chatInput = $('#chatMessageInput');
          if (chatInput) chatInput.value = text;
          $('#chatForm').dispatchEvent(new Event('submit'));
        }, 150);
      }
    }

    const replyBtn = $('#storyReplySendBtn');
    if (replyBtn) {
      replyBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        handleStoryReply();
      });
    }
    const replyInput = $('#storyReplyTextInput');
    if (replyInput) {
      replyInput.addEventListener('keydown', (e) => {
        e.stopPropagation();
        if (e.key === 'Enter') {
          e.preventDefault();
          handleStoryReply();
        }
      });
    }

    $('#deleteCurrentStoryBtn').addEventListener('click', async (e) => {
      const id = e.target.dataset.storyId;
      if (!id || !confirm('Delete this story?')) return;
      try {
        const res = await request(`/api/stories?id=${encodeURIComponent(id)}`, { method: 'DELETE' });
        showToast(res.message);
        closeStoryViewerModal();
        await loadStories();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // --- LOVEFEED POSTS FEATURE ---
    async function loadPosts() {
      if (!appState.auth || !appState.auth.is_authenticated) return;
      try {
        const data = await request('/api/posts');
        cachedPosts = data.posts || [];
        $('#feedCountBadge').textContent = cachedPosts.length;
        renderPosts();
      } catch (e) {}
    }

    function renderPosts() {
      const container = $('#feedPostsContainer');
      const auth = appState.auth || {};
      const currentUser = auth.username;
      const isAdmin = auth.role === 'admin';

      // Set create post avatar
      const myProfile = auth.profile || {};
      $('#createPostAvatar').innerHTML = renderAvatar(myProfile.avatar, currentUser, 42, myProfile.profile_photo);

      if (!cachedPosts.length) {
        container.innerHTML = `
          <div class="empty" style="padding:40px 20px">
            <span style="font-size:36px">📸</span>
            <h4 style="margin:8px 0 4px;font-size:16px">No posts on LoveFeed yet</h4>
            <p style="margin:0;color:var(--muted)">Be the first to share a lovely photo with the community!</p>
          </div>
        `;
        return;
      }

      container.innerHTML = cachedPosts.map(post => {
        const uObj = appState.users.find(u => u.username === post.author) || {};
        const isMine = post.author === currentUser;
        const canDelete = isMine || isAdmin;
        const isLiked = post.liked !== undefined ? post.liked : (post.likes && post.likes.includes(currentUser));
        const likesCount = post.likes_count !== undefined ? post.likes_count : (post.likes ? post.likes.length : 0);
        const timeStr = post.time_str || 'Recent';

        return `
          <article class="post-card" id="postCard_${escapeAttr(post.id)}">
            <header class="post-header">
              <div class="post-author-box">
                <div class="avatar" style="cursor:pointer" onclick="viewUserProfile('${escapeAttr(post.author)}')">
                  ${renderAvatar(post.author_avatar || uObj.avatar, post.author, 40, post.author_photo || uObj.profile_photo)}
                </div>
                <div>
                  <div class="post-author-name" style="cursor:pointer" onclick="viewUserProfile('${escapeAttr(post.author)}')">
                    ${escapeHtml(post.author)}
                    ${post.author_privacy === 'private' ? '<span class="privacy-badge private" style="margin-left:4px;font-size:9px">🔒 Private</span>' : ''}
                  </div>
                  <div class="post-time">${escapeHtml(timeStr)}</div>
                </div>
              </div>
              ${canDelete ? `<button class="mini-btn delete" data-delete-post="${escapeAttr(post.id)}" title="Delete post">🗑️</button>` : ''}
            </header>
            <div class="post-img-box">
              <img src="${escapeAttr(post.photo || post.image)}" alt="Post by ${escapeAttr(post.author)}" loading="lazy">
            </div>
            <div class="post-actions" style="display:flex;gap:10px;align-items:center">
              <button class="like-btn ${isLiked ? 'liked' : ''}" data-like-post="${escapeAttr(post.id)}">
                <span class="heart-icon">${isLiked ? '❤️' : '🤍'}</span>
                <span>${likesCount}</span>
              </button>
              ${!isMine ? `
                <button class="like-btn" data-chat="${escapeAttr(post.author)}" title="Send message to ${escapeAttr(post.author)}">
                  <span>💬</span>
                  <span style="font-weight:600">Chat</span>
                </button>
              ` : ''}
            </div>
            ${post.caption ? `
              <div class="post-caption-box">
                <strong>${escapeHtml(post.author)}</strong>${escapeHtml(post.caption)}
              </div>
            ` : ''}
          </article>
        `;
      }).join('');
    }

    $('#postImageUploadBox').addEventListener('click', () => {
      $('#postFileInput').click();
    });

    $('#postFileInput').addEventListener('change', async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      try {
        showToast('Processing photo...');
        selectedPostImageBase64 = await compressImage(file, 900, 0.78);
        $('#postSelectedPreview').src = selectedPostImageBase64;
        $('#postSelectedPreview').style.display = 'block';
        $('#postUploadPrompt').style.display = 'none';
        $('#cancelPostImgBtn').style.display = 'inline-block';
      } catch (err) {
        showToast(err.message, true);
      }
    });

    $('#cancelPostImgBtn').addEventListener('click', () => {
      selectedPostImageBase64 = null;
      $('#postFileInput').value = '';
      $('#postSelectedPreview').style.display = 'none';
      $('#postUploadPrompt').style.display = 'block';
      $('#cancelPostImgBtn').style.display = 'none';
    });

    $('#publishPostBtn').addEventListener('click', async () => {
      if (!selectedPostImageBase64) {
        showToast('Please select a photo to post!', true);
        return;
      }
      try {
        const caption = $('#postCaptionInput').value.trim();
        const res = await request('/api/posts', {
          method: 'POST',
          body: JSON.stringify({ image: selectedPostImageBase64, caption })
        });
        showToast(res.message);
        selectedPostImageBase64 = null;
        $('#postFileInput').value = '';
        $('#postCaptionInput').value = '';
        $('#postSelectedPreview').style.display = 'none';
        $('#postUploadPrompt').style.display = 'block';
        $('#cancelPostImgBtn').style.display = 'none';
        await loadPosts();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // --- REAL-TIME CHAT FEATURE ---
    let lastRenderedChatHash = '';
    window.liveChatPollTimer = null;

    function renderChatFriends() {
      const auth = appState.auth || {};
      const currentUser = auth.username;
      const list = $('#chatFriendsList');
      if (!list) return;

      const recentChats = appState.recent_chats || [];
      const friends = appState.users.filter(u => u.username !== currentUser && (u.is_friend || auth.role === 'admin'));
      const otherUsers = appState.users.filter(u => u.username !== currentUser && !u.is_friend && auth.role !== 'admin');
      const searchVal = ($('#chatUserSearchInput') ? $('#chatUserSearchInput').value.trim().toLowerCase() : '');

      let html = '';

      // Recent Conversations Section
      const filteredRecent = recentChats.filter(c => !searchVal || c.username.toLowerCase().includes(searchVal));
      if (filteredRecent.length > 0) {
        html += `
          <div style="margin-bottom:8px">
            <span style="font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px">Recent Conversations</span>
          </div>
        `;
        html += filteredRecent.map(c => `
          <div style="background:#fff;border:1.5px solid var(--line);border-radius:16px;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;box-shadow:var(--shadow);cursor:pointer;transition:transform 0.15s" data-chat="${escapeAttr(c.username)}">
            <div style="display:flex;align-items:center;gap:12px;overflow:hidden">
              <div class="avatar">${renderAvatar(c.avatar, c.username, 44, c.profile_photo)}</div>
              <div style="overflow:hidden">
                <div style="display:flex;align-items:center;gap:6px">
                  <strong style="color:var(--ink);font-size:15px">${escapeHtml(c.username)}</strong>
                  <span style="font-size:10px;color:var(--muted)">${escapeHtml(c.last_time || '')}</span>
                </div>
                <small style="color:var(--muted);display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:260px">${escapeHtml(c.last_message || 'Start chatting...')}</small>
              </div>
            </div>
            <button class="btn btn-primary" data-chat="${escapeAttr(c.username)}" style="font-size:12px;padding:6px 14px;background:linear-gradient(135deg,#ff4d88,#ff6584)">💬 Open</button>
          </div>
        `).join('');
      }

      // Friends & Connections Section
      const filteredFriends = friends.filter(f => !searchVal || f.username.toLowerCase().includes(searchVal));
      if (filteredFriends.length > 0) {
        html += `
          <div style="margin:${recentChats.length ? '16px' : '0'} 0 8px">
            <span style="font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px">Friends & Connections</span>
          </div>
        `;
        html += filteredFriends.map(f => `
          <div style="background:#fff;border:1px solid var(--line);border-radius:16px;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;box-shadow:var(--shadow)">
            <div style="display:flex;align-items:center;gap:12px">
              <div class="avatar">${renderAvatar(f.avatar, f.username, 44, f.profile_photo)}</div>
              <div>
                <strong style="color:var(--ink);font-size:15px">${escapeHtml(f.username)}</strong>
                <small style="color:var(--muted);display:block">${escapeHtml(f.city || 'Location not set')} · ${f.age ? f.age + ' yrs' : ''}</small>
              </div>
            </div>
            <button class="btn btn-primary" data-chat="${escapeAttr(f.username)}" style="font-size:13px;padding:8px 16px;background:linear-gradient(135deg,#ff4d88,#ff6584)">💬 Chat Now</button>
          </div>
        `).join('');
      }

      // Other Users on the platform (can search and chat with any user!)
      const showOthers = searchVal ? otherUsers.filter(u => u.username.toLowerCase().includes(searchVal)) : (friends.length === 0 ? otherUsers : otherUsers.slice(0, 10));
      if (showOthers.length > 0) {
        html += `
          <div style="margin:${(recentChats.length || friends.length) ? '16px' : '0'} 0 8px">
            <span style="font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px">${friends.length === 0 ? 'Start a Conversation with Someone 💕' : 'Other People to Chat With'}</span>
          </div>
        `;
        html += showOthers.map(u => `
          <div style="background:#fff;border:1px solid var(--line);border-radius:16px;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;box-shadow:var(--shadow)">
            <div style="display:flex;align-items:center;gap:12px">
              <div class="avatar">${renderAvatar(u.avatar, u.username, 44, u.profile_photo)}</div>
              <div>
                <strong style="color:var(--ink);font-size:15px">${escapeHtml(u.username)}</strong>
                <small style="color:var(--muted);display:block">${escapeHtml(u.city || 'Location not set')}</small>
              </div>
            </div>
            <button class="btn btn-primary" data-chat="${escapeAttr(u.username)}" style="font-size:13px;padding:8px 16px;background:linear-gradient(135deg,#ff4d88,#ff6584)">💬 Chat Now</button>
          </div>
        `).join('');
      }

      if (!html) {
        html = `
          <div class="empty" style="padding:28px 16px">
            <span style="font-size:32px">💬</span>
            <p style="font-weight:700;margin:8px 0 4px">No conversations yet.</p>
            <p style="margin:0 0 12px;color:var(--muted)">Select any person from Connections to start chatting in real time!</p>
            <button class="btn btn-primary" onclick="document.querySelector('#tabBtnConnections').click()">👥 View People</button>
          </div>
        `;
      }

      list.innerHTML = html;
    }

    const searchChatInput = $('#chatUserSearchInput');
    if (searchChatInput) {
      searchChatInput.addEventListener('input', renderChatFriends);
    }

    function openChatWith(username) {
      if (!username) return;
      const currentUser = (appState.auth && appState.auth.username) || '';
      if (username === currentUser) {
        showToast('You cannot chat with yourself 💕', true);
        return;
      }

      // Close other modals if open
      const vpModal = $('#viewProfileModal');
      if (vpModal) vpModal.classList.remove('open');
      const svModal = $('#storyViewerModal');
      if (svModal && svModal.classList.contains('open')) {
        closeStoryViewerModal();
      }

      const targetUser = (appState.users && appState.users.find(u => u.username === username)) || { username };
      activeChatPartner = username;
      lastRenderedChatHash = '';

      $('#chatPartnerAvatar').innerHTML = renderAvatar(targetUser.avatar, username, 38, targetUser.profile_photo);
      $('#chatPartnerName').textContent = username;
      $('#chatMessageInput').value = '';
      $('#liveChatModal').classList.add('open');

      loadChatMessages(false);

      // Start dedicated high-speed real-time polling (every 750ms)
      clearInterval(window.liveChatPollTimer);
      window.liveChatPollTimer = setInterval(() => {
        if (activeChatPartner && $('#liveChatModal').classList.contains('open')) {
          loadChatMessages(true);
        } else {
          clearInterval(window.liveChatPollTimer);
        }
      }, 750);

      setTimeout(() => $('#chatMessageInput').focus(), 150);
    }
    window.openChatWith = openChatWith;

    async function loadChatMessages(isSilent = false) {
      if (!activeChatPartner) return;
      try {
        const data = await request(`/api/chat?with=${encodeURIComponent(activeChatPartner)}`);
        const messages = data.messages || [];
        const msgList = $('#chatMessageList');
        const currentUser = (appState.auth && appState.auth.username) || '';

        if (data.friend_avatar || data.friend_photo) {
          const avatarBox = $('#chatPartnerAvatar');
          if (avatarBox) {
            avatarBox.innerHTML = renderAvatar(data.friend_avatar, activeChatPartner, 38, data.friend_photo);
          }
        }

        const newHash = JSON.stringify(messages);
        if (newHash === lastRenderedChatHash) return;
        lastRenderedChatHash = newHash;

        if (!messages.length) {
          msgList.innerHTML = `
            <div class="empty" style="margin:auto">
              <span>💕</span>
              <p style="margin:6px 0 0">No messages yet. Say hello to ${escapeHtml(activeChatPartner)}!</p>
            </div>
          `;
          return;
        }

        const wasAtBottom = msgList.scrollHeight - msgList.scrollTop <= msgList.clientHeight + 80;

        msgList.innerHTML = messages.map(m => {
          const isMine = m.from === currentUser;
          const timeStr = m.time_str || (m.timestamp ? new Date(m.timestamp * 1000).toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' }) : '');
          return `
            <div class="chat-bubble ${isMine ? 'mine' : 'theirs'}">
              <div>${escapeHtml(m.text)}</div>
              <span class="chat-msg-time">${escapeHtml(timeStr)}</span>
            </div>
          `;
        }).join('');

        if (!isSilent || wasAtBottom) {
          msgList.scrollTop = msgList.scrollHeight;
        }
      } catch (err) {
        if (!isSilent) showToast(err.message, true);
      }
    }

    $('#chatForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const input = $('#chatMessageInput');
      const text = input.value.trim();
      if (!text || !activeChatPartner) return;
      input.value = '';

      // Optimistic instant render for snappy feel
      const msgList = $('#chatMessageList');
      const emptyMsg = msgList.querySelector('.empty');
      if (emptyMsg) emptyMsg.remove();

      const nowTimeStr = new Date().toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' });
      const tempBubble = document.createElement('div');
      tempBubble.className = 'chat-bubble mine';
      tempBubble.innerHTML = `<div>${escapeHtml(text)}</div><span class="chat-msg-time">${escapeHtml(nowTimeStr)}</span>`;
      msgList.appendChild(tempBubble);
      msgList.scrollTop = msgList.scrollHeight;

      try {
        await request('/api/chat', {
          method: 'POST',
          body: JSON.stringify({ to: activeChatPartner, text })
        });
        await loadChatMessages(true);
      } catch (err) {
        showToast(err.message, true);
      }
    });

    function closeLiveChatModal() {
      clearInterval(window.liveChatPollTimer);
      $('#liveChatModal').classList.remove('open');
      activeChatPartner = null;
      lastRenderedChatHash = '';
    }

    $('#closeChatModal').addEventListener('click', closeLiveChatModal);

    $('#liveChatModal').addEventListener('click', (e) => {
      if (e.target === $('#liveChatModal')) {
        closeLiveChatModal();
      }
    });

    // --- VIEW PROFILE DETAILS MODAL (WITH PRIVACY NORMS & LOCK) ---
    async function viewUserProfile(username) {
      try {
        const data = await request('/api/view', { method: 'POST', body: JSON.stringify({ username }) });
        const auth = appState.auth || {};
        const isAdmin = auth.role === 'admin';
        const isSelf = data.username === auth.username;

        $('#viewAvatar').innerHTML = renderAvatar(data.avatar, data.username, 68, data.profile_photo);
        $('#viewUsername').innerHTML = `${escapeHtml(data.username)} ${data.role === 'admin' ? '<span style="font-size:11px;padding:2px 7px;border-radius:10px;background:#fef3c7;color:#92400e;font-weight:800">ADMIN</span>' : ''}`;
        $('#viewMeta').textContent = `${escapeHtml(data.city || 'Location not set')} · ${data.age ? data.age + ' years old' : 'Age not set'}`;

        const priv = data.privacy || 'public';
        $('#viewPrivacyBadgeContainer').innerHTML = `<span class="privacy-badge ${priv}">${priv === 'private' ? '🔒 Private Account' : '🌐 Public Account'}</span>`;

        const lockBanner = $('#viewPrivateLockBanner');
        const contentSection = $('#viewProfileContentSection');

        if (data.is_private_locked) {
          lockBanner.style.display = 'block';
          contentSection.style.display = 'none';
        } else {
          lockBanner.style.display = 'none';
          contentSection.style.display = 'block';

          $('#viewBio').textContent = data.bio ? `"${data.bio}"` : 'No bio added yet 💕';
          $('#viewFriendsCount').textContent = data.friends_count;
          $('#viewMutualCount').textContent = data.mutual_friends ? data.mutual_friends.length : 0;

          const mutualList = $('#viewMutualList');
          if (data.mutual_friends && data.mutual_friends.length) {
            mutualList.innerHTML = `<strong>Mutual connections:</strong> ${data.mutual_friends.map(m => escapeHtml(m)).join(', ')}`;
          } else {
            mutualList.innerHTML = '';
          }

          // User posts
          const postsBox = $('#viewUserPostsContainer');
          const postsList = $('#viewUserPostsList');
          if (data.posts && data.posts.length) {
            postsBox.style.display = 'block';
            postsList.innerHTML = data.posts.map(p => `
              <div style="aspect-ratio:1;border-radius:10px;overflow:hidden;background:#eee">
                <img src="${escapeAttr(p.image)}" style="width:100%;height:100%;object-fit:cover" alt="Post">
              </div>
            `).join('');
          } else {
            postsBox.style.display = 'none';
          }
        }

        const actionBox = $('#viewActionContainer');
        if (isSelf) {
          actionBox.innerHTML = '<span class="pill">This is your profile</span>';
        } else {
          let chatBtnHtml = `<button class="btn btn-primary" id="modalStartChatBtn" data-chat="${escapeAttr(data.username)}" style="background:linear-gradient(135deg,#ff4d88,#ff6584)">💬 Chat with ${escapeHtml(data.username)}</button>`;
          let connectBtnHtml = '';
          if (data.is_friend) {
            connectBtnHtml = `<button class="mini-btn delete" id="modalDisconnectBtn" data-target="${escapeAttr(data.username)}">Remove Connection</button>`;
          } else if (data.has_pending_outgoing) {
            connectBtnHtml = '<span class="pill">⏳ Connection Request Pending...</span>';
          } else if (data.has_pending_incoming) {
            connectBtnHtml = `
              <button class="pill accept" id="modalAcceptBtn" data-from="${escapeAttr(data.username)}">♡ Accept</button>
              <button class="pill reject" id="modalRejectBtn" data-from="${escapeAttr(data.username)}">✕ Decline</button>
            `;
          } else {
            connectBtnHtml = `<button class="btn btn-soft" id="modalSendReqBtn" data-target="${escapeAttr(data.username)}">💌 Send Request</button>`;
          }
          let adminDeleteHtml = '';
          if (isAdmin && data.username !== 'admin') {
            adminDeleteHtml = `<button class="mini-btn delete" id="modalDeleteProfileBtn" data-delete-user="${escapeAttr(data.username)}" style="background:#fee2e2;color:#dc2626;border:1px solid #fca5a5;padding:6px 14px;border-radius:20px;font-weight:700">🗑️ Delete Account</button>`;
          }
          actionBox.innerHTML = `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:center">${chatBtnHtml} ${connectBtnHtml} ${adminDeleteHtml}</div>`;
        }

        $('#viewProfileModal').classList.add('open');
      } catch (err) {
        showToast(err.message, true);
      }
    }

    $('#closeViewModal').addEventListener('click', () => {
      $('#viewProfileModal').classList.remove('open');
    });

    $('#viewActionContainer').addEventListener('click', async (e) => {
      const sendBtn = e.target.closest('#modalSendReqBtn');
      const acceptBtn = e.target.closest('#modalAcceptBtn');
      const rejectBtn = e.target.closest('#modalRejectBtn');
      const discBtn = e.target.closest('#modalDisconnectBtn');
      const chatBtn = e.target.closest('#modalStartChatBtn');
      const delUserBtn = e.target.closest('#modalDeleteProfileBtn');

      try {
        if (delUserBtn) {
          e.stopPropagation();
          const target = delUserBtn.dataset.deleteUser;
          if (!confirm(`Are you sure you want to permanently delete profile "${target}"? This will delete their account, posts, stories, and chats.`)) return;
          const res = await request(`/api/users/${encodeURIComponent(target)}`, { method: 'DELETE' });
          showToast(res.message);
          $('#viewProfileModal').classList.remove('open');
          await refresh();
          return;
        }
        if (chatBtn) {
          e.stopPropagation();
          const target = chatBtn.dataset.chat;
          $('#viewProfileModal').classList.remove('open');
          openChatWith(target);
          return;
        }
        if (sendBtn) {
          const target = sendBtn.dataset.target;
          const res = await request('/api/requests', { method: 'POST', body: JSON.stringify({ to: target }) });
          showToast(res.message);
          $('#viewProfileModal').classList.remove('open');
          await refresh();
        }
        if (acceptBtn) {
          const from = acceptBtn.dataset.from;
          const res = await request('/api/requests/accept', { method: 'POST', body: JSON.stringify({ from, to: appState.auth.username }) });
          showToast(res.message);
          $('#viewProfileModal').classList.remove('open');
          await refresh();
        }
        if (rejectBtn) {
          const from = rejectBtn.dataset.from;
          const res = await request('/api/requests/reject', { method: 'POST', body: JSON.stringify({ from, to: appState.auth.username }) });
          showToast(res.message);
          $('#viewProfileModal').classList.remove('open');
          await refresh();
        }
        if (discBtn) {
          const target = discBtn.dataset.target;
          const res = await request('/api/friends', { method: 'DELETE', body: JSON.stringify({ user_a: appState.auth.username, user_b: target }) });
          showToast(res.message);
          $('#viewProfileModal').classList.remove('open');
          await refresh();
        }
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // --- MAIN RENDER FUNCTION ---
    function render() {
      const auth = appState.auth || {};
      const isAuth = Boolean(auth.is_authenticated);
      const isAdmin = auth.role === 'admin';
      const currentUser = auth.username;

      // Toggle Views
      $('#authView').style.display = isAuth ? 'none' : 'flex';
      $('#mainDashboard').style.display = isAuth ? 'block' : 'none';
      $('#notifBtn').style.display = isAuth ? 'inline-flex' : 'none';
      $('#topbarChatBtn').style.display = isAuth ? 'inline-flex' : 'none';
      $('#myProfileBtn').style.display = isAuth ? 'inline-flex' : 'none';
      $('#logoutBtn').style.display = isAuth ? 'inline-flex' : 'none';
      $('#undoBtn').style.display = isAuth && isAdmin ? 'inline-flex' : 'none';

      // Topbar Pill
      const pillContainer = $('#authPillContainer');
      if (isAuth) {
        const miniAv = renderAvatar(auth.profile ? auth.profile.avatar : null, auth.username, 24);
        if (isAdmin) {
          pillContainer.innerHTML = `<span class="admin-pill" onclick="openMyProfileModal()" style="display:inline-flex;align-items:center;gap:6px;cursor:pointer">${miniAv} <span>👑 Admin: ${escapeHtml(auth.username)}</span></span>`;
        } else {
          pillContainer.innerHTML = `<span class="user-pill" onclick="openMyProfileModal()" style="display:inline-flex;align-items:center;gap:6px;cursor:pointer">${miniAv} <span>💕 ${escapeHtml(auth.username)}</span></span>`;
        }
      } else {
        pillContainer.innerHTML = `<span class="user-pill" style="color:var(--muted)">🔒 Not logged in</span>`;
      }

      // Notifications Count & List
      const notifs = appState.notifications || [];
      $('#notifBadge').textContent = notifs.length;
      renderNotifications();

      if (!isAuth) return;

      // Personalized Hero
      if (isAdmin) {
        $('#heroEyebrow').textContent = '👑 ADMINISTRATOR CONTROL CENTER';
        $('#heroTitle').textContent = 'Full Network & Connection Management';
        $('#heroSubtitle').textContent = 'Monitor all profiles, oversee connection requests in real-time, and manage system operations.';
      } else {
        $('#heroEyebrow').textContent = `WELCOME BACK, ${auth.username.toUpperCase()} 💕`;
        $('#heroTitle').textContent = 'Make room for the connections that feel right.';
        $('#heroSubtitle').textContent = 'Discover your people, nurture new sparks, and keep every meaningful connection close.';
      }

      // Calculate friend counts
      const myUserObj = appState.users.find(u => u.username === currentUser);
      const myFriendsCount = (myUserObj && myUserObj.friends && myUserObj.friends.length) || 0;
      const discoverCount = appState.users.filter(u => u.username !== currentUser && !u.is_friend).length;

      // Stats
      const stats = appState.stats || {};
      $('#statUsersLabel').textContent = isAdmin ? 'Total Platform Users' : 'My Friends';
      $('#statUsers').textContent = isAdmin ? (stats.users || 0) : myFriendsCount;
      $('#statFriends').textContent = stats.friendships || 0;
      $('#statPending').textContent = appState.requests.length;
      $('#statPendingLabel').textContent = isAdmin ? 'Global Pending Requests' : 'Requests for Me';
      $('#requestBadge').textContent = appState.requests.length;

      // View Filters (Normal user gets Friends vs Discover tabs)
      if (isAdmin) {
        $('#userTabsContainer').style.display = 'none';
        $('#gridEyebrow').textContent = 'Platform Profiles';
        $('#gridTitle').textContent = `All Users (${appState.users.length})`;
      } else {
        $('#userTabsContainer').style.display = 'flex';
        $('#myFriendsCount').textContent = myFriendsCount;
        $('#discoverCount').textContent = discoverCount;
      }

      // Admin vs User Form Visibility
      $('#adminAddSection').style.display = isAdmin ? 'block' : 'none';
      $('#adminConnectRow').style.display = isAdmin ? 'grid' : 'none';
      $('#userConnectField').style.display = isAdmin ? 'none' : 'block';
      $('#directConnectBtn').style.display = isAdmin ? 'inline-flex' : 'none';
      $('#removeFriendBtn').style.display = isAdmin ? 'inline-flex' : 'none';
      $('#processBtn').style.display = isAdmin ? 'inline-flex' : 'none';

      renderUsers();
      renderSelects();
      renderRequests();
      renderRecent();
      loadRecommendations();
      loadStories();
      if (currentMainTab === 'feed') loadPosts();
      if (currentMainTab === 'chats') renderChatFriends();
    }

    function renderNotifications() {
      const list = $('#notifList');
      const notifs = appState.notifications || [];
      if (!notifs.length) {
        list.innerHTML = '<div class="empty">No new notifications.</div>';
        return;
      }
      const myName = (appState.auth && appState.auth.username) || '';
      list.innerHTML = notifs.map(n => {
        let sender = '';
        const match = (n.text || '').match(/(?:from|by|accepted|with)\s+([A-Za-z0-9_]+)/i) || (n.text || '').match(/^([A-Za-z0-9_]+)\s+sent/i);
        if (match && match[1]) sender = match[1];

        return `
          <div class="notif-item" style="display:flex;align-items:center;justify-content:space-between;gap:8px">
            <p style="margin:0;flex:1">${escapeHtml(n.text)}</p>
            <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
              ${sender && sender !== myName ? `<button type="button" class="mini-btn" data-chat="${escapeAttr(sender)}" style="font-size:10px;padding:3px 8px;background:#ffe4ee;color:#bd3265;border:1px solid #fbcfe8;border-radius:12px;cursor:pointer">💬 Chat</button>` : ''}
              <span class="notif-tag ${escapeAttr(n.type)}">${escapeHtml(n.type.toUpperCase())}</span>
            </div>
          </div>
        `;
      }).join('');
    }

    function renderUsers() {
      const auth = appState.auth || {};
      const isAdmin = auth.role === 'admin';
      const currentUser = auth.username;
      const query = $('#searchInput').value.toLowerCase().trim();

      let usersToDisplay = [];
      if (isAdmin) {
        // Admin sees all users
        usersToDisplay = appState.users;
      } else {
        // Normal user: check tab
        if (currentTab === 'friends') {
          usersToDisplay = appState.users.filter(u => u.is_friend && u.username !== currentUser);
        } else {
          usersToDisplay = appState.users.filter(u => !u.is_friend && u.username !== currentUser);
        }
      }

      usersToDisplay = usersToDisplay.filter(u => u.username.toLowerCase().includes(query));
      const grid = $('#userGrid');

      if (!usersToDisplay.length) {
        if (!isAdmin && currentTab === 'friends') {
          grid.innerHTML = `
            <div class="empty" style="grid-column:1/-1;padding:28px 16px">
              <span style="font-size:32px">💕</span>
              <p style="font-weight:700;margin:8px 0 4px">You don't have any connections yet!</p>
              <p style="margin:0 0 14px">Switch to <strong>Discover New People</strong> to find sparks and send requests.</p>
              <button class="btn btn-primary" onclick="document.querySelector('#tabDiscover').click()">🔍 Discover People</button>
            </div>
          `;
        } else {
          grid.innerHTML = '<div class="empty" style="grid-column:1/-1">No profiles match your search.</div>';
        }
        return;
      }

      grid.innerHTML = usersToDisplay.map((user, index) => {
        const isSelf = user.username === currentUser;
        const isFriend = user.is_friend;
        const isAdminUser = user.role === 'admin';

        let badge = '';
        if (isAdminUser) badge = '<span style="font-size:10px;padding:2px 6px;border-radius:10px;background:#fef3c7;color:#92400e;font-weight:800;margin-left:4px">ADMIN</span>';
        if (isSelf) badge += '<span style="font-size:10px;padding:2px 6px;border-radius:10px;background:#ffe4ee;color:#bd3265;font-weight:800;margin-left:4px">YOU</span>';

        let actionBtns = `<button class="mini-btn view-btn" data-view="${escapeAttr(user.username)}">👁️ View</button>`;

        if (!isSelf) {
          actionBtns += `<button class="mini-btn chat-btn" data-chat="${escapeAttr(user.username)}" style="background:linear-gradient(135deg,#ff4d88,#ff6584);color:#fff;border:none">💬 Chat</button>`;
          if (isFriend) {
            actionBtns += `<span style="font-size:11px;font-weight:700;color:#059669;margin-left:4px">Connected ♡</span>`;
          } else {
            actionBtns += `<button class="mini-btn req" data-req="${escapeAttr(user.username)}">💌 Request</button>`;
          }
        }

        if (isAdmin && user.username !== 'admin') {
          actionBtns += `<button class="mini-btn delete" data-delete="${escapeAttr(user.username)}">Delete</button>`;
        }

        return `
          <article class="user-card">
            <div class="user-top">
              <div class="avatar ${isAdminUser ? 'admin' : (index % 3 === 1 ? 'alt' : '')}">${renderAvatar(user.avatar, user.username, 44, user.profile_photo)}</div>
              <div style="flex:1;min-width:0">
                <p class="user-name">${escapeHtml(user.username)} ${badge}</p>
                <div class="user-meta">${escapeHtml(user.city || 'Location not set')} · ${user.age || 'Age not set'}</div>
              </div>
            </div>
            ${user.bio ? `<p class="user-bio-snip">"${escapeHtml(user.bio)}"</p>` : ''}
            <div class="count">${user.friends.length} connection${user.friends.length === 1 ? '' : 's'}</div>
            <div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px">${actionBtns}</div>
          </article>
        `;
      }).join('');
    }

    function renderSelects() {
      const auth = appState.auth || {};
      const currentUser = auth.username;

      // Exclude yourself and existing friends for normal users
      const otherUsers = appState.users.filter(u => u.username !== currentUser && !u.is_friend);
      const recipientOptions = otherUsers.map(u => `<option value="${escapeAttr(u.username)}">${escapeHtml(u.username)}</option>`).join('');

      const selectUserB = $('#user_b');
      const curB = selectUserB.value;
      selectUserB.innerHTML = recipientOptions || '<option value="">No other profiles available</option>';
      if (otherUsers.some(u => u.username === curB)) selectUserB.value = curB;

      // Admin selects
      const allOptions = appState.users.map(u => `<option value="${escapeAttr(u.username)}">${escapeHtml(u.username)}</option>`).join('');
      const selectA = $('#user_a');
      const selectBAdmin = $('#user_b_admin');
      if (selectA) {
        const curA = selectA.value;
        selectA.innerHTML = allOptions;
        if (appState.users.some(u => u.username === curA)) selectA.value = curA;
      }
      if (selectBAdmin) {
        const curBAdmin = selectBAdmin.value;
        selectBAdmin.innerHTML = allOptions;
        if (appState.users.some(u => u.username === curBAdmin)) selectBAdmin.value = curBAdmin;
      }
    }

    function renderRequests() {
      const auth = appState.auth || {};
      const currentUser = auth.username;
      const isAdmin = auth.role === 'admin';
      const list = $('#requestList');

      if (!appState.requests.length) {
        list.innerHTML = '<div class="empty">No pending connection requests.</div>';
        return;
      }

      list.innerHTML = appState.requests.map(req => {
        const isForMe = req.to === currentUser;
        const isFromMe = req.from === currentUser;

        let rightSide = '';
        if (isForMe || isAdmin) {
          rightSide = `
            <div class="req-btns">
              <button class="pill accept" data-accept-from="${escapeAttr(req.from)}" data-accept-to="${escapeAttr(req.to)}">♡ Accept</button>
              <button class="pill reject" data-reject-from="${escapeAttr(req.from)}" data-reject-to="${escapeAttr(req.to)}">✕ Reject</button>
            </div>
          `;
        } else if (isFromMe) {
          rightSide = `<span class="pill">Waiting...</span>`;
        } else {
          rightSide = `<span class="pill">Pending</span>`;
        }

        return `
          <div class="request">
            <p>
              <strong>${escapeHtml(req.from)}</strong> wants to connect with <strong>${escapeHtml(req.to)}</strong><br>
              <span>${isForMe ? 'Waiting for your acceptance 💕' : (isFromMe ? 'Sent by you' : 'In queue')}</span>
            </p>
            ${rightSide}
          </div>
        `;
      }).join('');
    }

    function renderRecent() {
      const list = $('#recentList');
      list.innerHTML = appState.recently_viewed.length
        ? appState.recently_viewed.map(name => `
            <div class="recent-item">
              <span><strong>${escapeHtml(name)}</strong></span>
              <button class="mini-btn view-btn" data-view="${escapeAttr(name)}" style="padding:3px 7px;font-size:11px">View</button>
            </div>
          `).join('')
        : '<div class="empty">Profiles you view will appear here.</div>';
    }

    async function loadRecommendations() {
      const auth = appState.auth || {};
      if (!auth.is_authenticated) return;
      const username = auth.username;
      const box = $('#recommendations');
      try {
        const data = await request(`/api/recommendations?user=${encodeURIComponent(username)}`);
        box.innerHTML = data.recommendations.length
          ? data.recommendations.map(item => `
              <div class="rec-item">
                <span><strong>${escapeHtml(item.username)}</strong></span>
                <div style="display:flex;align-items:center;gap:6px">
                  <small>${item.score} mutual connection${item.score === 1 ? '' : 's'}</small>
                  <button class="mini-btn view-btn" data-view="${escapeAttr(item.username)}" style="padding:3px 7px;font-size:11px">View</button>
                </div>
              </div>
            `).join('')
          : '<div class="empty">No mutual recommendations yet. Connect with more friends to see matches!</div>';
      } catch (err) {
        box.innerHTML = '<div class="empty">Could not load recommendations.</div>';
      }
    }

    // --- REAL-TIME LIVE SYNC (every 1.5s) ---
    async function syncState() {
      if (isSyncing) return;
      isSyncing = true;
      try {
        const fresh = await request('/api/state');
        const freshHash = JSON.stringify(fresh);
        if (freshHash !== lastStateHash) {
          lastStateHash = freshHash;
          appState = fresh;
          render();
        }
        // Real-time chat live update if chat modal is open
        if (activeChatPartner && $('#liveChatModal').classList.contains('open')) {
          loadChatMessages(true);
        }
        // Auto-refresh stories tray
        if (appState.auth && appState.auth.is_authenticated) {
          loadStories();
        }
      } catch (e) {
        // retry
      } finally {
        isSyncing = false;
      }
    }

    async function refresh() {
      appState = await request('/api/state');
      lastStateHash = JSON.stringify(appState);
      render();
    }

    // --- EVENT LISTENERS ---
    $('#searchInput').addEventListener('input', renderUsers);

    // Send Connection Request
    $('#sendRequestBtn').addEventListener('click', async () => {
      try {
        const auth = appState.auth || {};
        const isAdmin = auth.role === 'admin';
        const userA = isAdmin ? $('#user_a').value : auth.username;
        const userB = isAdmin ? $('#user_b_admin').value : $('#user_b').value;

        if (!userB) {
          showToast('Please select who to send the request to.', true);
          return;
        }
        const result = await request('/api/requests', {
          method: 'POST',
          body: JSON.stringify({ from: userA, to: userB })
        });
        showToast(result.message);
        await refresh();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // Accept / Reject Connection Request (from list)
    $('#requestList').addEventListener('click', async (e) => {
      const acceptBtn = e.target.closest('[data-accept-from]');
      const rejectBtn = e.target.closest('[data-reject-from]');

      try {
        if (acceptBtn) {
          const fromUser = acceptBtn.dataset.acceptFrom;
          const toUser = acceptBtn.dataset.acceptTo;
          const result = await request('/api/requests/accept', {
            method: 'POST',
            body: JSON.stringify({ from: fromUser, to: toUser })
          });
          showToast(result.message);
          await refresh();
        }
        if (rejectBtn) {
          const fromUser = rejectBtn.dataset.rejectFrom;
          const toUser = rejectBtn.dataset.rejectTo;
          const result = await request('/api/requests/reject', {
            method: 'POST',
            body: JSON.stringify({ from: fromUser, to: toUser })
          });
          showToast(result.message);
          await refresh();
        }
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // Process next request (Admin queue button)
    $('#processBtn').addEventListener('click', async () => {
      try {
        const result = await request('/api/requests/process', { method: 'POST', body: '{}' });
        showToast(result.message);
        await refresh();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // Admin direct connect
    $('#friendForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const data = Object.fromEntries(new FormData(e.target));
        const result = await request('/api/friends', { method: 'POST', body: JSON.stringify(data) });
        showToast(result.message);
        await refresh();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // Admin remove connection
    $('#removeFriendBtn').addEventListener('click', async () => {
      try {
        const form = $('#friendForm');
        const data = Object.fromEntries(new FormData(form));
        const result = await request('/api/friends', { method: 'DELETE', body: JSON.stringify(data) });
        showToast(result.message);
        await refresh();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // Admin add user form
    $('#adminUserForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const data = Object.fromEntries(new FormData(e.target));
        const result = await request('/api/users', { method: 'POST', body: JSON.stringify(data) });
        e.target.reset();
        showToast(result.message);
        await refresh();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // Admin undo button
    $('#undoBtn').addEventListener('click', async () => {
      try {
        const result = await request('/api/undo', { method: 'POST', body: '{}' });
        showToast(result.message);
        await refresh();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // Delegate Clicks for View, Request, Delete, Chat
    document.addEventListener('click', async (e) => {
      const chat = e.target.closest('[data-chat]');
      const view = e.target.closest('[data-view]');
      const req = e.target.closest('[data-req]');
      const del = e.target.closest('[data-delete]');

      try {
        if (chat) {
          const target = chat.dataset.chat;
          if (target) {
            const vpModal = $('#viewProfileModal');
            if (vpModal) vpModal.classList.remove('open');
            const stvModal = $('#storyViewersModal');
            if (stvModal) stvModal.classList.remove('open');
            const svModal = $('#storyViewerModal');
            if (svModal && svModal.classList.contains('open')) {
              closeStoryViewerModal();
            }
            openChatWith(target);
          }
          return;
        }
        if (view) {
          const username = view.dataset.view;
          viewUserProfile(username);
        }
        if (req) {
          const target = req.dataset.req;
          const selectB = appState.auth.role === 'admin' ? $('#user_b_admin') : $('#user_b');
          if (selectB) selectB.value = target;
          $('#connectionSection').scrollIntoView({ behavior: 'smooth' });
          showToast(`Selected "${target}". Click "Send Request" to connect! 💕`);
        }
        if (del) {
          const target = del.dataset.delete;
          if (confirm(`Are you sure you want to permanently delete profile "${target}"? This will delete their account, posts, stories, and chats.`)) {
            const result = await request(`/api/users/${encodeURIComponent(target)}`, {
              method: 'DELETE'
            });
            showToast(result.message);
            await refresh();
          }
        }
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // --- AVATAR STUDIO MODAL & BUTTON EVENT HANDLERS ---
    $('#closeAvatarStudio').addEventListener('click', closeAvatarStudioModal);
    $('#cancelAvatarBtn').addEventListener('click', closeAvatarStudioModal);

    $('#openAvatarStudioBtn').addEventListener('click', openAvatarStudio);
    $('#myAvatar').addEventListener('click', openAvatarStudio);

    // Click handler for swatch and chip selection
    $('#avatarStudioModal').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-prop]');
      if (!btn) return;
      const prop = btn.dataset.prop;
      const val = btn.dataset.val;
      if (currentEditingAvatar && prop && val) {
        currentEditingAvatar[prop] = val;
        updateStudioPreview();
      }
    });

    // Randomize
    $('#randomAvatarBtn').addEventListener('click', () => {
      const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
      currentEditingAvatar = {
        skin: pick(AVATAR_OPTIONS.skins).id,
        hairColor: pick(AVATAR_OPTIONS.hairColors).id,
        hairStyle: pick(AVATAR_OPTIONS.hairStyles).id,
        expression: pick(AVATAR_OPTIONS.expressions).id,
        accessory: pick(AVATAR_OPTIONS.accessories).id,
        outfit: pick(AVATAR_OPTIONS.outfits).id,
        outfitColor: pick(AVATAR_OPTIONS.outfitColors).id,
        bg: pick(AVATAR_OPTIONS.backgrounds).id
      };
      updateStudioPreview();
    });

    // Presets
    $('#presetRomanticBtn').addEventListener('click', () => {
      currentEditingAvatar = {
        skin: '#f3cbb0',
        hairColor: '#ff5c98',
        hairStyle: 'wavy',
        expression: 'heart_eyes',
        accessory: 'flower',
        outfit: 'hoodie',
        outfitColor: '#ff4d88',
        bg: 'pink'
      };
      updateStudioPreview();
    });

    $('#presetCoolBtn').addEventListener('click', () => {
      currentEditingAvatar = {
        skin: '#e8b896',
        hairColor: '#1f1b24',
        hairStyle: 'spikes',
        expression: 'shades',
        accessory: 'cap',
        outfit: 'jacket',
        outfitColor: '#2b2d42',
        bg: 'ocean'
      };
      updateStudioPreview();
    });

    $('#presetRoyalBtn').addEventListener('click', () => {
      currentEditingAvatar = {
        skin: '#ffdfc4',
        hairColor: '#c98a3c',
        hairStyle: 'bun',
        expression: 'sparkle',
        accessory: 'crown',
        outfit: 'collar',
        outfitColor: '#845ec2',
        bg: 'snapchat'
      };
      updateStudioPreview();
    });

    // Save avatar
    $('#saveAvatarBtn').addEventListener('click', async () => {
      try {
        const res = await request('/api/profile/avatar', {
          method: 'POST',
          body: JSON.stringify({ avatar: currentEditingAvatar })
        });
        showToast(res.message);
        closeAvatarStudioModal();
        await refresh();
        if ($('#myProfileModal').classList.contains('open')) {
          openMyProfileModal();
        }
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // Initial load & Start background live sync
    refresh().catch(err => showToast(err.message, true));
    setInterval(syncState, 1500);
  </script>
</body>
</html>'''


def main():
    with STATE_LOCK:
        dsa.load_data(silent=True)
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"LoveLoop with Notifications & Bio running on port {PORT}")
    print("Press Ctrl+C to stop the server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping LoveLoop.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
