# Customer Dashboard — Comprehensive Plan

## Overview
Build a **customer-facing web dashboard** where customers can:
- Login with **phone number** (password-based in dev, OTP-based in prod)
- View only **their conversation history** (linked to Profile)
- **Initiate new chats** from the UI (text → AI response)
- See **call summaries** and conversation details

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Frontend (Django Template + HTMX/JS)        │
│  • Login Page (phone + password/OTP)                            │
│  • Dashboard (conversation list)                                 │
│  • Chat Interface (real-time messaging)                          │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│                     Django REST API / Views                      │
│  • auth/login (phone + password OR OTP validation)              │
│  • auth/send-otp (Telegram)                                     │
│  • api/conversations/ (list user's calls)                       │
│  • api/chat/ (POST new chat turn)                               │
│  • api/conversation/{id}/history (GET turns)                    │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│                  Django ORM + Models                             │
│  • Profile (phone, email, name, etc.)                           │
│  • Call (links to Profile, stores history)                      │
│  • TranscriptTurn (individual chat turns)                       │
│  • OTPSession (temp storage for OTP validation) [NEW]           │
│  • WebChatSession (UI-based chat, separate from phone calls)    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Backend Setup 🔵

### 1.1 Create Authentication Models
**File:** `telephony/models.py`

```python
class OTPSession(models.Model):
    phone = CharField(max_length=20)
    otp_code = CharField(max_length=6)
    created_at = DateTimeField(auto_now_add=True)
    expires_at = DateTimeField()
    is_verified = BooleanField(default=False)
    
    class Meta:
        indexes = [
            models.Index(fields=['phone', 'created_at'])
        ]

class WebChatSession(models.Model):
    """UI-initiated conversations (separate from phone calls)"""
    profile = ForeignKey(Profile, on_delete=models.CASCADE)
    call = ForeignKey(Call, on_delete=models.SET_NULL, null=True, blank=True)
    initiated_by = CharField(max_length=20, choices=[('phone', 'Phone'), ('web', 'Web')])
    is_active = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
```

**Acceptance Criterion:** Migrations created and models accessible in Django shell.

---

### 1.2 Add Django Session Authentication
**File:** `telephony/backends.py` [NEW]

```python
from django.contrib.auth.backends import ModelBackend
from telephony.models import Profile

class PhoneAuthBackend(ModelBackend):
    """Authenticate via phone number instead of username."""
    
    def authenticate(self, request, phone=None, password=None, **kwargs):
        # Development mode: allow any phone + password "123456"
        if settings.DEBUG and password == "123456":
            profile, _ = Profile.objects.get_or_create(
                phone=phone,
                defaults={'name': 'Test User'}
            )
            return profile
        
        # Production: should not reach here (use OTP instead)
        return None
```

**Acceptance Criterion:** Backend callable, returns Profile object on valid auth.

---

### 1.3 Create API Views (DRF or Generic Django Views)
**File:** `telephony/views.py`

```python
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login
from django.http import JsonResponse
import json

# ─────────────────────────────────────────────────────────────────
# Authentication Endpoints
# ─────────────────────────────────────────────────────────────────

@require_http_methods(["POST"])
def login_view(request):
    """
    POST: {phone: "+91...", password_or_otp: "123456" or "000000"}
    Returns: {"success": bool, "message": str, "profile": {...}}
    """
    data = json.loads(request.body)
    phone = data.get('phone', '').strip()
    pwd_or_otp = data.get('password_or_otp', '').strip()
    
    if not phone or not pwd_or_otp:
        return JsonResponse({'success': False, 'error': 'Phone and password required'}, status=400)
    
    # Normalize phone
    from telephony.phone_numbers import to_e164
    phone = to_e164(phone)
    
    # Dev mode: accept password "123456"
    if settings.DEBUG and pwd_or_otp == "123456":
        profile, _ = Profile.objects.get_or_create(phone=phone)
        # Create session
        request.session['profile_id'] = profile.id
        return JsonResponse({
            'success': True,
            'profile': {'id': profile.id, 'phone': profile.phone, 'name': profile.name}
        })
    
    # Prod mode: validate OTP
    if not settings.DEBUG:
        otp_session = OTPSession.objects.filter(
            phone=phone,
            otp_code=pwd_or_otp,
            expires_at__gt=now(),
        ).first()
        
        if not otp_session:
            return JsonResponse({'success': False, 'error': 'Invalid OTP'}, status=401)
        
        otp_session.is_verified = True
        otp_session.save()
        
        profile, _ = Profile.objects.get_or_create(phone=phone)
        request.session['profile_id'] = profile.id
        return JsonResponse({
            'success': True,
            'profile': {'id': profile.id, 'phone': profile.phone, 'name': profile.name}
        })

@require_http_methods(["POST"])
def send_otp(request):
    """
    POST: {phone: "+91..."}
    Generates OTP, sends via Telegram, returns success.
    Only works in PROD (DEBUG mode returns static OTP).
    """
    data = json.loads(request.body)
    phone = to_e164(data.get('phone', ''))
    
    # Generate OTP
    import random
    otp_code = f"{random.randint(0, 999999):06d}"
    
    # Save to DB
    otp_session = OTPSession.objects.create(
        phone=phone,
        otp_code=otp_code,
        expires_at=now() + timedelta(minutes=10)
    )
    
    # Send via Telegram
    if not settings.DEBUG:
        send_telegram_message(
            f"QWR Dashboard OTP: {otp_code}\nExpires in 10 minutes"
        )
        return JsonResponse({'success': True, 'message': 'OTP sent to Telegram'})
    else:
        # Dev: return OTP in response (for testing)
        return JsonResponse({'success': True, 'otp_for_dev': otp_code})

# ─────────────────────────────────────────────────────────────────
# Conversation API Endpoints
# ─────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def list_conversations(request):
    """
    GET: /api/conversations/
    Returns list of user's calls with summaries.
    """
    if 'profile_id' not in request.session:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    profile = Profile.objects.get(id=request.session['profile_id'])
    calls = Call.objects.filter(profile=profile).order_by('-created_at')
    
    data = []
    for call in calls:
        summary_text = call.summary.summary_text if hasattr(call, 'summary') else 'No summary'
        data.append({
            'id': call.id,
            'call_sid': call.call_sid,
            'created_at': call.created_at.isoformat(),
            'duration': call.duration,
            'status': call.status,
            'summary': summary_text[:200],  # First 200 chars
        })
    
    return JsonResponse({'conversations': data})

@require_http_methods(["GET"])
def get_conversation_detail(request, call_id):
    """
    GET: /api/conversation/{call_id}/
    Returns full conversation with all turns.
    """
    if 'profile_id' not in request.session:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    profile = Profile.objects.get(id=request.session['profile_id'])
    try:
        call = Call.objects.get(id=call_id, profile=profile)
    except Call.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)
    
    turns = []
    for turn in call.turns.all().order_by('seq_number'):
        turns.append({
            'speaker': turn.speaker,
            'text': turn.text,
            'latency_ms': turn.latency_ms,
        })
    
    return JsonResponse({
        'call': {
            'id': call.id,
            'created_at': call.created_at.isoformat(),
            'duration': call.duration,
        },
        'turns': turns,
    })

# ─────────────────────────────────────────────────────────────────
# Web Chat API (Initiating new conversation from UI)
# ─────────────────────────────────────────────────────────────────

@require_http_methods(["POST"])
def send_chat_message(request):
    """
    POST: {message: "hello"}
    Processes user message through AI agent, returns reply.
    Creates new Call + TranscriptTurns as needed.
    """
    if 'profile_id' not in request.session:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    data = json.loads(request.body)
    user_message = data.get('message', '').strip()
    
    if not user_message:
        return JsonResponse({'error': 'Message cannot be empty'}, status=400)
    
    profile = Profile.objects.get(id=request.session['profile_id'])
    
    # Get or create web chat session
    web_session = WebChatSession.objects.filter(
        profile=profile,
        is_active=True,
        initiated_by='web'
    ).first()
    
    if not web_session:
        # Create new call for this web session
        call = Call.objects.create(
            call_sid=f"web-{profile.id}-{uuid.uuid4().hex[:8]}",
            profile=profile,
            direction=Call.Direction.OUTGOING,
            status='active',
        )
        web_session = WebChatSession.objects.create(
            profile=profile,
            call=call,
            initiated_by='web',
        )
    else:
        call = web_session.call
    
    # Send through AI agent
    from ai_agent.agent import QWRAgent
    agent = QWRAgent(
        call_id=call.id,
        call_sid=call.call_sid,
        stream_sid="web-chat",
    )
    
    # Get AI response (synchronously for now, could be async)
    user_transcript, ai_reply = asyncio.run(
        agent.chat(user_text=user_message)
    )
    
    # Store in DB
    seq_num = call.turns.count() + 1
    TranscriptTurn.objects.create(
        call=call,
        seq_number=seq_num,
        speaker='user',
        text=user_message,
    )
    TranscriptTurn.objects.create(
        call=call,
        seq_number=seq_num + 1,
        speaker='assistant',
        text=ai_reply,
    )
    
    return JsonResponse({
        'user_message': user_message,
        'ai_reply': ai_reply,
        'call_id': call.id,
    })
```

**Acceptance Criterion:** All endpoints callable via curl/Postman, return correct JSON.

---

### 1.4 Update URLs
**File:** `qwr_voicebot/urls.py`

```python
from telephony import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    
    # Authentication
    path("api/auth/login", views.login_view, name="login"),
    path("api/auth/send-otp", views.send_otp, name="send_otp"),
    
    # Customer API
    path("api/conversations/", views.list_conversations, name="conversations"),
    path("api/conversation/<int:call_id>/", views.get_conversation_detail, name="conversation_detail"),
    path("api/chat/send", views.send_chat_message, name="send_chat"),
    
    # UI Dashboard
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("dashboard/login", views.dashboard_login_view, name="dashboard_login"),
]
```

**Acceptance Criterion:** All routes registered, accessible at `/api/*` and `/dashboard/*`.

---

## Phase 2: Frontend (Django Templates) 🟢

### 2.1 Login Page
**File:** `telephony/templates/login.html` [NEW]

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QWR Dashboard Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .login-container {
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.1);
            width: 100%;
            max-width: 400px;
            padding: 40px;
        }
        h1 { text-align: center; margin-bottom: 30px; font-size: 24px; }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: #333;
        }
        input, button {
            width: 100%;
            padding: 12px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 14px;
        }
        input { margin-bottom: 10px; }
        input:focus { outline: none; border-color: #667eea; box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1); }
        button {
            background: #667eea;
            color: white;
            border: none;
            font-weight: 600;
            cursor: pointer;
            margin-top: 10px;
        }
        button:hover { background: #5568d3; }
        .error { color: #e74c3c; font-size: 13px; margin-top: 5px; }
        .info { text-align: center; font-size: 12px; color: #666; margin-top: 15px; }
        .send-otp-btn { background: #27ae60; margin-bottom: 10px; }
        .send-otp-btn:hover { background: #229954; }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>🎤 QWR Dashboard</h1>
        
        <div id="loginForm">
            <div class="form-group">
                <label>Phone Number</label>
                <input type="tel" id="phone" placeholder="+91 9876543210" required>
            </div>
            
            <div id="devMode" style="display: none;">
                <p class="info">🔧 Dev Mode: Use password <strong>123456</strong></p>
                <div class="form-group">
                    <label>Password</label>
                    <input type="password" id="password" placeholder="123456" value="123456">
                </div>
                <button onclick="login()">Login</button>
            </div>
            
            <div id="prodMode" style="display: none;">
                <button class="send-otp-btn" onclick="sendOTP()">Send OTP via Telegram</button>
                <div class="form-group">
                    <label>Enter OTP (6 digits)</label>
                    <input type="text" id="otp" placeholder="000000" maxlength="6">
                </div>
                <button onclick="verifyOTP()">Verify & Login</button>
            </div>
        </div>
        
        <div id="messageBox"></div>
    </div>

    <script>
        // Detect dev vs prod on page load
        function initPage() {
            fetch('/api/health/')
                .then(r => r.json())
                .then(data => {
                    // If response contains is_dev flag
                    if (data.is_dev) {
                        document.getElementById('devMode').style.display = 'block';
                    } else {
                        document.getElementById('prodMode').style.display = 'block';
                    }
                });
        }

        async function sendOTP() {
            const phone = document.getElementById('phone').value;
            if (!phone) { showMessage('Please enter phone number', 'error'); return; }

            const res = await fetch('/api/auth/send-otp', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone })
            });
            const data = await res.json();
            if (data.success) {
                showMessage('OTP sent! Check Telegram', 'success');
                if (data.otp_for_dev) {
                    showMessage(`Dev OTP: ${data.otp_for_dev}`, 'info');
                }
            } else {
                showMessage(data.error || 'Failed to send OTP', 'error');
            }
        }

        async function login() {
            const phone = document.getElementById('phone').value;
            const password = document.getElementById('password').value;
            
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone, password_or_otp: password })
            });
            const data = await res.json();
            if (data.success) {
                window.location.href = '/dashboard/';
            } else {
                showMessage(data.error || 'Login failed', 'error');
            }
        }

        async function verifyOTP() {
            const phone = document.getElementById('phone').value;
            const otp = document.getElementById('otp').value;
            
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone, password_or_otp: otp })
            });
            const data = await res.json();
            if (data.success) {
                window.location.href = '/dashboard/';
            } else {
                showMessage(data.error || 'OTP verification failed', 'error');
            }
        }

        function showMessage(msg, type) {
            const box = document.getElementById('messageBox');
            box.innerHTML = `<div class="${type}">${msg}</div>`;
        }

        window.onload = initPage;
    </script>
</body>
</html>
```

**Acceptance Criterion:** Login page loads, allows phone + password entry, submits to API.

---

### 2.2 Dashboard Page
**File:** `telephony/templates/dashboard.html` [NEW]

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QWR Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f7fa; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
        h1 { font-size: 24px; }
        .logout-btn { background: #e74c3c; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; }
        .main { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .conversations-panel, .chat-panel { background: white; border-radius: 8px; padding: 20px; }
        .conversations-list { list-style: none; }
        .conversation-item { padding: 12px; border-bottom: 1px solid #eee; cursor: pointer; transition: background 0.2s; }
        .conversation-item:hover { background: #f9f9f9; }
        .conversation-item.active { background: #e8f4f8; border-left: 3px solid #667eea; }
        .chat-header { font-weight: 600; margin-bottom: 15px; }
        .chat-messages { height: 400px; overflow-y: auto; border: 1px solid #eee; border-radius: 6px; padding: 15px; margin-bottom: 15px; background: #fafafa; }
        .message { margin-bottom: 12px; padding: 10px 12px; border-radius: 6px; }
        .message.user { background: #667eea; color: white; margin-left: 40px; text-align: right; }
        .message.assistant { background: #e8e8e8; margin-right: 40px; }
        .chat-input { display: flex; gap: 10px; }
        .chat-input input { flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 6px; }
        .chat-input button { background: #667eea; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; }
        .loading { text-align: center; color: #999; font-size: 12px; padding: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📱 QWR Dashboard</h1>
            <button class="logout-btn" onclick="logout()">Logout</button>
        </header>

        <div class="main">
            <!-- Left: Conversations List -->
            <div class="conversations-panel">
                <h2>Your Conversations</h2>
                <ul class="conversations-list" id="conversationsList"></ul>
                <div class="loading">Loading...</div>
            </div>

            <!-- Right: Chat Area -->
            <div class="chat-panel">
                <div class="chat-header">New Message</div>
                <div class="chat-messages" id="chatMessages"></div>
                <div class="chat-input">
                    <input type="text" id="userInput" placeholder="Type your message..." onkeypress="if(event.key==='Enter') sendMessage()">
                    <button onclick="sendMessage()">Send</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentCallId = null;

        async function loadConversations() {
            const res = await fetch('/api/conversations/');
            const data = await res.json();
            
            const list = document.getElementById('conversationsList');
            list.innerHTML = '';
            
            if (data.conversations.length === 0) {
                list.innerHTML = '<li style="padding: 20px; text-align: center; color: #999;">No conversations yet</li>';
                return;
            }
            
            data.conversations.forEach(conv => {
                const item = document.createElement('li');
                item.className = 'conversation-item';
                item.innerHTML = `
                    <div><strong>${new Date(conv.created_at).toLocaleDateString()}</strong></div>
                    <div style="font-size: 12px; color: #666;">${conv.summary}</div>
                `;
                item.onclick = () => loadConversation(conv.id);
                list.appendChild(item);
            });
        }

        async function loadConversation(callId) {
            currentCallId = callId;
            const res = await fetch(`/api/conversation/${callId}/`);
            const data = await res.json();
            
            const chatBox = document.getElementById('chatMessages');
            chatBox.innerHTML = '';
            
            data.turns.forEach(turn => {
                const msg = document.createElement('div');
                msg.className = `message ${turn.speaker}`;
                msg.textContent = turn.text;
                chatBox.appendChild(msg);
            });
            
            chatBox.scrollTop = chatBox.scrollHeight;
        }

        async function sendMessage() {
            const input = document.getElementById('userInput');
            const message = input.value.trim();
            
            if (!message) return;
            
            // Add to UI immediately
            const chatBox = document.getElementById('chatMessages');
            const msg = document.createElement('div');
            msg.className = 'message user';
            msg.textContent = message;
            chatBox.appendChild(msg);
            input.value = '';
            
            // Send to API
            const res = await fetch('/api/chat/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message })
            });
            const data = await res.json();
            
            if (data.ai_reply) {
                const aiMsg = document.createElement('div');
                aiMsg.className = 'message assistant';
                aiMsg.textContent = data.ai_reply;
                chatBox.appendChild(aiMsg);
                currentCallId = data.call_id;
            }
            
            chatBox.scrollTop = chatBox.scrollHeight;
        }

        function logout() {
            fetch('/api/auth/logout', { method: 'POST' });
            window.location.href = '/dashboard/login';
        }

        window.onload = loadConversations;
    </script>
</body>
</html>
```

**Acceptance Criterion:** Dashboard loads, shows conversation list on left, chat on right. Can click to load history.

---

### 2.3 View to Render Dashboard
**File:** `telephony/views.py` [ADD]

```python
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods

def dashboard_view(request):
    """Render main dashboard page."""
    if 'profile_id' not in request.session:
        return redirect('dashboard_login')
    
    profile = Profile.objects.get(id=request.session['profile_id'])
    return render(request, 'dashboard.html', {'profile': profile})

def dashboard_login_view(request):
    """Render login page."""
    return render(request, 'login.html')
```

**Acceptance Criterion:** `/dashboard/` shows dashboard when authenticated, redirects to login otherwise.

---

## Phase 3: Configuration & Integration 🔵

### 3.1 Add Settings
**File:** `qwr_voicebot/settings.py` [UPDATE]

```python
# Add to TEMPLATES
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'telephony' / 'templates'],
        'APP_DIRS': True,
        ...
    }
]

# Session config (already default, but explicit)
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 86400 * 7  # 7 days

# Add to INSTALLED_APPS if not present
INSTALLED_APPS = [
    ...
    'django.contrib.sessions',
    ...
]
```

**Acceptance Criterion:** Settings parseable, migrations run without error.

---

### 3.2 Add Telegram Integration
**File:** `telephony/notifications.py` [UPDATE/CREATE]

```python
import httpx
from ai_agent.config import settings
import logging

logger = logging.getLogger(__name__)

async def send_telegram_otp(phone: str, otp_code: str) -> bool:
    """Send OTP via Telegram."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram not configured")
        return False
    
    message = f"QWR Dashboard OTP for {phone}: {otp_code}\nExpires in 10 minutes."
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                params={
                    'chat_id': settings.telegram_chat_id,
                    'text': message
                }
            )
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send Telegram OTP: {e}")
        return False
```

**Acceptance Criterion:** Function callable, sends message to configured Telegram chat.

---

## Phase 4: Testing 🟡

### 4.1 Manual Test Flow (Dev Mode)
1. Navigate to `http://localhost:8000/dashboard/login`
2. Enter any phone number: `+919876543210`
3. Enter password: `123456`
4. Click Login → should redirect to `/dashboard/`
5. See "Your Conversations" list (empty on first login)
6. Type a message in chat box, hit Send
7. AI should reply in real-time
8. Message should persist in history

### 4.2 Prod Mode Test
1. Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`
2. Set `DJANGO_DEBUG=false`
3. Navigate to login page
4. Enter phone, click "Send OTP"
5. OTP arrives on Telegram
6. Enter OTP, login works

---

## File Structure Summary

```
telephony/
├── models.py                          [UPDATE: Add OTPSession, WebChatSession]
├── views.py                           [UPDATE: Add auth, API, chat endpoints]
├── notifications.py                   [UPDATE: Add send_telegram_otp]
├── backends.py                        [NEW: PhoneAuthBackend]
├── templates/
│   ├── login.html                     [NEW]
│   └── dashboard.html                 [NEW]

qwr_voicebot/
├── urls.py                            [UPDATE: Add new routes]
├── settings.py                        [UPDATE: Add TEMPLATES, SESSION config]
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Django sessions (not JWT) | Simpler, no token management needed; works well with Django templates |
| SQLite OTPSession (not cache) | Persistent, surveyable in admin, replay-attack-resistant |
| Sync views (not async) | Simpler initial implementation; can optimize later |
| SMS-based auth in dev (password) | Testing without Telegram dependency |
| Web chat separate from phone calls | Allows UI chat independent of voice calls; stored in same Call model |
| Telegram (not SMS/Email) | Admin uses Telegram already; no SMS costs |

---

## Success Criteria ✅

- [ ] Customer can login with phone + password (dev) or phone + OTP (prod)
- [ ] Only sees own conversation history
- [ ] Can initiate new chat from UI
- [ ] AI responds in real-time
- [ ] Chat persisted to Call/TranscriptTurn
- [ ] OTP sent via Telegram (prod only)
- [ ] Logout clears session
- [ ] Mobile-friendly UI
- [ ] All endpoints return correct JSON

---

## Timeline Estimate

| Phase | Effort | Time |
|-------|--------|------|
| 1.1 Models | Small | 1 hr |
| 1.2 Auth Backend | Small | 1 hr |
| 1.3 API Views | Medium | 3-4 hrs |
| 1.4 URLs | Small | 30 min |
| 2.1 Login Template | Small | 1.5 hrs |
| 2.2 Dashboard Template | Medium | 2 hrs |
| 2.3 View Functions | Small | 30 min |
| 3.1 Settings | Small | 30 min |
| 3.2 Telegram Integration | Small | 1 hr |
| 4 Testing | Medium | 2 hrs |
| **Total** | | **12-14 hours** |

