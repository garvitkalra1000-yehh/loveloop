# 💕 LoveLoop - Social Media Friend Management System

LoveLoop is an interactive, full-stack Social Media & Friend Management web application built with Python. It features role-based authentication, real-time live sync, friend discovery, notifications, visual profiles with customizable avatars, stories, and chats.

---

## ✨ Features

- **🌸 Love Pink UI / UX**: Modern, responsive design with smooth animations.
- **🔐 Role-Based Authentication**: Support for both standard users and administrative controls.
- **👥 Friend & Connection Management**: Send, accept, or reject friend requests with pending queues.
- **🔍 People Discovery & Mutual Friends**: Discover new users, view mutual connections, and inspect profiles.
- **🎨 Custom Avatar Studio**: In-app avatar generator with accessories and styles.
- **💬 Real-Time Updates**: Live background polling for notifications and friend updates.
- **💾 Local Persistence**: Automatic JSON storage (`users.json`) so state persists across runs.

---

## 🚀 Quick Start (Local)

### Prerequisites
- Python 3.8 or higher (No third-party packages required for core app)

### Running the App
```bash
python web_app.py
```
Open your browser and navigate to:
```
http://localhost:8000
```

---

## 🌐 Deployment

### Deploying to Render
1. Push this repository to GitHub.
2. Create a new **Web Service** on [Render](https://render.com).
3. Connect your repository.
4. Set:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python web_app.py`
5. Click **Deploy**.

---

## 📂 Project Structure

- `web_app.py` - Core HTTP server, REST API endpoints, and embedded frontend UI.
- `dsa.py` - Data structures, friendship graph operations, queue, and persistence helpers.
- `users.json` - Local database for users, relationships, and notifications.
- `requirements.txt` - Project dependencies.
- `Dockerfile` & `Procfile` - Container and cloud hosting configurations.
