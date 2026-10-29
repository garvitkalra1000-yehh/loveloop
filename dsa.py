"""
Social Media Friend Management System
--------------------------------------
Single-file, simple procedural version (no classes).

NEW: Auto-storage
    - Data is loaded automatically from users.json when the program starts.
    - Data is saved automatically after every change (add/delete user,
      add/remove friend, undo, friend requests) and again on exit.
    So you never have to re-enter users or friends again.
"""

import json
import os
from collections import deque


# ---------- Data Storage ----------

# file is stored next to this .py file, so it works from any folder
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")

# dictionary for storing user details
# username -> {"age": ..., "city": ..., "friends": set()}
users = {}

# queue (FIFO) for pending friend requests -> each item is (from, to)
friend_requests = deque()

# stack (LIFO) for undo -> each item is (action_type, data)
action_stack = []

# list for recently viewed profiles, most recent first
recently_viewed = []

# chats: canonical_key "min(u1,u2):max(u1,u2)" -> list of messages
chats = {}

# posts: list of user photo posts
posts = []

# stories: list of active stories
stories = []


# ---------- SAVE / LOAD (JSON FILE HANDLING) ----------

def save_data(silent=False):
    """Write users and pending friend requests to users.json."""

    data = {
        "users": {
            username: {
                "age": u.get("age"),
                "city": u.get("city"),
                "bio": u.get("bio", ""),
                "friends": sorted(u.get("friends", set())),   # set -> list for JSON
                "password": u.get("password", "123456"),
                "role": u.get("role", "admin" if username == "admin" else "user"),
                "notifications": u.get("notifications", []),
                "avatar": u.get("avatar", {}),
                "profile_photo": u.get("profile_photo", ""),
                "privacy": u.get("privacy", "public"),
            }
            for username, u in users.items()
        },
        "friend_requests": [list(r) for r in friend_requests],
        "chats": chats,
        "posts": posts,
        "stories": stories
    }

    try:
        # write to a temp file first, then replace -> file never ends up half-written
        temp_file = DATA_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        try:
            os.replace(temp_file, DATA_FILE)
        except OSError:
            import shutil
            shutil.copyfile(temp_file, DATA_FILE)
            if os.path.exists(temp_file):
                os.remove(temp_file)

        if not silent:
            print("Data saved successfully to 'users.json'.")
    except Exception as e:
        print(f"Could not save data: {e}")


def load_data(silent=False):
    """Read users and pending friend requests from users.json."""

    global users, chats, posts, stories

    if not os.path.exists(DATA_FILE):
        if not silent:
            print("File 'users.json' not found.")
        return

    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)

        # support the older format too (file was just a dict of users)
        if "users" in data and "friend_requests" in data:
            user_data = data["users"]
            request_data = data["friend_requests"]
        else:
            user_data = data
            request_data = []

        loaded_users = {
            username: {
                "age": u.get("age"),
                "city": u.get("city"),
                "bio": u.get("bio", ""),
                "friends": set(u.get("friends", [])),   # list -> set
                "password": u.get("password", "123456"),
                "role": u.get("role", "admin" if username == "admin" else "user"),
                "notifications": u.get("notifications", []),
                "avatar": u.get("avatar", {}),
                "profile_photo": u.get("profile_photo", ""),
                "privacy": u.get("privacy", "public"),
            }
            for username, u in user_data.items()
        }

        if "admin" not in loaded_users:
            loaded_users["admin"] = {
                "age": "99",
                "city": "AdminHQ",
                "bio": "System Administrator",
                "friends": set(),
                "password": "admin123",
                "role": "admin",
                "notifications": [],
                "avatar": {},
                "profile_photo": "",
                "privacy": "public",
            }

        chats = data.get("chats", {})
        posts = data.get("posts", [])
        stories = data.get("stories", [])

    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        print("Saved file is damaged or unreadable. Starting with empty data.")
        return

    users = loaded_users

    friend_requests.clear()
    for r in request_data:
        if r[0] in users and r[1] in users:
            friend_requests.append((r[0], r[1]))

    # old history no longer matches the loaded data, so clear it
    action_stack.clear()
    recently_viewed.clear()

    if not silent:
        print("Data loaded successfully from 'users.json'.")


# ---------- USER MANAGEMENT ----------

def add_user():

    username = input("Enter username: ").strip()

    if not username:
        print("Username cannot be empty.")
        return

    if username in users:
        print(f"User '{username}' already exists.")
        return

    age = input("Enter age (optional): ").strip()
    city = input("Enter city (optional): ").strip()

    users[username] = {
        "age": age if age else None,
        "city": city if city else None,
        "friends": set()
    }

    action_stack.append(("ADD_USER", username))

    print(f"User '{username}' added successfully.")


def delete_user():

    username = input("Enter username to delete: ").strip()

    if username not in users:
        print(f"User '{username}' not found.")
        return

    # keep a copy so this can be undone
    removed_user = users[username]

    # remove this user from all their friends' friend sets
    for friend in removed_user["friends"]:
        users[friend]["friends"].discard(username)

    del users[username]

    action_stack.append(("DELETE_USER", (username, removed_user)))

    print(f"User '{username}' deleted successfully.")


def search_user():

    username = input("Enter username to search: ").strip()

    if username not in users:
        print(f"User '{username}' not found.")
        return

    user = users[username]

    # bonus: track profile view
    view_profile(username)

    print(f"\nUsername : {username}")
    print(f"Age      : {user['age'] if user['age'] else '-'}")
    print(f"City     : {user['city'] if user['city'] else '-'}")
    print(f"Friends  : {len(user['friends'])}")


def display_users():

    if not users:
        print("No users in the network yet.")
        return

    print(f"\n{'Username':<15}{'Age':<8}{'City':<15}{'Friends':<8}")
    print("-" * 46)

    for username in sorted(users):
        u = users[username]
        age = u["age"] if u["age"] else "-"
        city = u["city"] if u["city"] else "-"
        print(f"{username:<15}{str(age):<8}{str(city):<15}{len(u['friends']):<8}")


# ---------- FRIEND MANAGEMENT ----------

def add_friend():

    user_a = input("Enter first username: ").strip()
    user_b = input("Enter second username: ").strip()

    if user_a not in users or user_b not in users:
        print("Both users must exist.")
        return

    if user_a == user_b:
        print("A user cannot be friends with themselves.")
        return

    if user_b in users[user_a]["friends"]:
        print(f"'{user_a}' and '{user_b}' are already friends.")
        return

    users[user_a]["friends"].add(user_b)
    users[user_b]["friends"].add(user_a)

    action_stack.append(("ADD_FRIEND", (user_a, user_b)))

    print(f"'{user_a}' and '{user_b}' are now friends.")


def remove_friend():

    user_a = input("Enter first username: ").strip()
    user_b = input("Enter second username: ").strip()

    if user_a not in users or user_b not in users:
        print("Both users must exist.")
        return

    if user_b not in users[user_a]["friends"]:
        print(f"'{user_a}' and '{user_b}' are not friends.")
        return

    users[user_a]["friends"].discard(user_b)
    users[user_b]["friends"].discard(user_a)

    action_stack.append(("REMOVE_FRIEND", (user_a, user_b)))

    print(f"'{user_a}' and '{user_b}' are no longer friends.")


def show_friends():

    username = input("Enter username: ").strip()

    if username not in users:
        print(f"User '{username}' not found.")
        return

    view_profile(username)

    friend_list = sorted(users[username]["friends"])

    print(f"\nFriends of {username}:")

    if not friend_list:
        print("  (no friends yet)")
    else:
        for f in friend_list:
            print(f"  - {f}")


def mutual_friends():

    user_a = input("Enter first username: ").strip()
    user_b = input("Enter second username: ").strip()

    if user_a not in users or user_b not in users:
        print("Both users must exist.")
        return

    # set intersection
    common = users[user_a]["friends"] & users[user_b]["friends"]

    print(f"\nMutual friends of {user_a} and {user_b}:")

    if not common:
        print("  (none)")
    else:
        for f in sorted(common):
            print(f"  - {f}")


def recommend_friends():

    username = input("Enter username: ").strip()

    if username not in users:
        print(f"User '{username}' not found.")
        return

    direct_friends = users[username]["friends"]
    scores = {}

    for friend in direct_friends:
        for fof in users[friend]["friends"]:
            if fof != username and fof not in direct_friends:
                scores[fof] = scores.get(fof, 0) + 1

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    print(f"\nFriend recommendations for {username}:")

    if not ranked:
        print("  (none)")
    else:
        for user, score in ranked[:5]:
            print(f"  - {user} ({score} mutual connection(s))")


# ---------- NETWORK STATISTICS ----------

def network_statistics():

    total_users = len(users)
    total_friendships = sum(len(u["friends"]) for u in users.values()) // 2
    avg_friends = round(total_friendships * 2 / total_users, 2) if total_users > 0 else 0

    print("\n--- Network Statistics ---")
    print("Total Users       :", total_users)
    print("Total Friendships :", total_friendships)
    print("Avg Friends/User  :", avg_friends)


# ---------- UNDO (STACK) ----------

def undo_last_action():

    if not action_stack:
        print("No actions to undo.")
        return

    action_type, data = action_stack.pop()

    if action_type == "ADD_USER":
        username = data
        del users[username]
        print(f"Undo: Removed user '{username}'.")

    elif action_type == "DELETE_USER":
        username, user_data = data
        users[username] = user_data
        for friend in user_data["friends"]:
            users[friend]["friends"].add(username)
        print(f"Undo: Restored user '{username}'.")

    elif action_type == "ADD_FRIEND":
        user_a, user_b = data
        users[user_a]["friends"].discard(user_b)
        users[user_b]["friends"].discard(user_a)
        print(f"Undo: Removed friendship between '{user_a}' and '{user_b}'.")

    elif action_type == "REMOVE_FRIEND":
        user_a, user_b = data
        users[user_a]["friends"].add(user_b)
        users[user_b]["friends"].add(user_a)
        print(f"Undo: Restored friendship between '{user_a}' and '{user_b}'.")


# ---------- BONUS FEATURES ----------

def send_friend_request():

    from_user = input("From username: ").strip()
    to_user = input("To username: ").strip()

    if from_user not in users or to_user not in users:
        print("Both users must exist.")
        return

    if from_user == to_user:
        print("A user cannot send a friend request to themselves.")
        return

    if to_user in users[from_user]["friends"]:
        print(f"'{from_user}' and '{to_user}' are already friends.")
        return

    if (from_user, to_user) in friend_requests:
        print("This friend request is already pending.")
        return

    friend_requests.append((from_user, to_user))
    print(f"Friend request sent from '{from_user}' to '{to_user}'.")


def process_next_friend_request():

    if not friend_requests:
        print("No pending friend requests.")
        return

    from_user, to_user = friend_requests.popleft()  # FIFO

    if from_user not in users or to_user not in users:
        print("Request skipped: one of the users no longer exists.")
        return

    if from_user == to_user:
        print("Request skipped: a user cannot be friends with themselves.")
        return

    if to_user in users[from_user]["friends"]:
        print(f"'{from_user}' and '{to_user}' are already friends.")
        return

    users[from_user]["friends"].add(to_user)
    users[to_user]["friends"].add(from_user)

    action_stack.append(("ADD_FRIEND", (from_user, to_user)))

    print(f"Processed request: '{from_user}' and '{to_user}' are now friends.")


def view_profile(username):
    # helper for recently-viewed list, not a menu option itself
    if username in recently_viewed:
        recently_viewed.remove(username)
    recently_viewed.insert(0, username)
    del recently_viewed[10:]


def show_recently_viewed():

    print("\nRecently Viewed Profiles:")

    if not recently_viewed:
        print("  (none)")
    else:
        for u in recently_viewed:
            print(f"  - {u}")


def top_five_connected():

    ranking = [(username, len(u["friends"])) for username, u in users.items()]
    ranking.sort(key=lambda x: x[1], reverse=True)

    print("\nTop 5 Most Connected Users:")

    if not ranking:
        print("  (none)")
    else:
        for rank, (username, count) in enumerate(ranking[:5], start=1):
            print(f"  {rank}. {username} - {count} friend(s)")


def search_by_prefix():

    prefix = input("Enter prefix: ").strip().lower()

    results = sorted([u for u in users if u.lower().startswith(prefix)])

    print(f"\nUsers starting with '{prefix}':")

    if not results:
        print("  (none)")
    else:
        for u in results:
            print(f"  - {u}")


# ---------- MENUS ----------

def print_main_menu():

    print("\n" + "=" * 40)
    print("SOCIAL MEDIA FRIEND MANAGEMENT")
    print("=" * 40)
    print("1. Add User")
    print("2. Delete User")
    print("3. Search User")
    print("4. Display Users")
    print("5. Add Friend")
    print("6. Remove Friend")
    print("7. Show Friends")
    print("8. Mutual Friends")
    print("9. Recommend Friends")
    print("10. Network Statistics")
    print("11. Undo Last Action")
    print("12. Save Data")
    print("13. Load Data")
    print("14. Bonus Features")
    print("15. Exit")


def print_bonus_menu():

    print("\n" + "=" * 15 + " BONUS FEATURES " + "=" * 15)
    print("1. Send Friend Request")
    print("2. Process Next Friend Request")
    print("3. Show Recently Viewed Profiles")
    print("4. Top 5 Most Connected Users")
    print("5. Search by Username Prefix")
    print("6. Back to Main Menu")


def bonus_menu():

    while True:

        print_bonus_menu()

        choice = input("Enter Choice: ").strip()

        if choice == "1":
            send_friend_request()
            save_data(silent=True)      # auto-save (pending requests are stored too)
        elif choice == "2":
            process_next_friend_request()
            save_data(silent=True)      # auto-save
        elif choice == "3":
            show_recently_viewed()
        elif choice == "4":
            top_five_connected()
        elif choice == "5":
            search_by_prefix()
        elif choice == "6":
            break
        else:
            print("Invalid choice, try again.")


# ---------- MAIN MENU ----------

def main():

    # AUTO-LOAD: bring back everything saved last time
    load_data(silent=True)
    if users:
        print(f"Loaded {len(users)} user(s) from saved data.")

    while True:

        print_main_menu()

        choice = input("Enter Choice: ").strip()

        if choice == "1":
            add_user()
            save_data(silent=True)      # AUTO-SAVE after every change
        elif choice == "2":
            delete_user()
            save_data(silent=True)
        elif choice == "3":
            search_user()
        elif choice == "4":
            display_users()
        elif choice == "5":
            add_friend()
            save_data(silent=True)
        elif choice == "6":
            remove_friend()
            save_data(silent=True)
        elif choice == "7":
            show_friends()
        elif choice == "8":
            mutual_friends()
        elif choice == "9":
            recommend_friends()
        elif choice == "10":
            network_statistics()
        elif choice == "11":
            undo_last_action()
            save_data(silent=True)
        elif choice == "12":
            save_data()
        elif choice == "13":
            load_data()
        elif choice == "14":
            bonus_menu()
        elif choice == "15":
            save_data(silent=True)      # final save on exit
            print("Data saved. Thank you for using Social Media Friend Management System!")
            break
        else:
            print("Invalid choice, try again.")


# ---------- PROGRAM START ----------

if __name__ == "__main__":
    main()
