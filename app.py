
import os
import pandas as pd
from flask import Flask, jsonify, request, redirect, url_for, session
from flask_cors import CORS
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
from authlib.integrations.flask_client import OAuth
import jwt
import secrets
import database
import engine

# --- 1. APP & DB INITIALIZATION ---
app = Flask(__name__)

# --- Load Config from Environment Variables ---
app.config['SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY')
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')
FRONTEND_URL = os.environ.get('FRONTEND_URL') # Set by Render

# Enable CORS
CORS(app, resources={r"/api/*": {"origins": [FRONTEND_URL]}})

# --- 2. AUTHENTICATION SETUP (GOOGLE OAUTH & JWT) ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=app.config['GOOGLE_CLIENT_ID'],
    client_secret=app.config['GOOGLE_CLIENT_SECRET'],
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

def get_db():
    """Helper to get a fresh db connection."""
    return database.initialize_database()

def serialize_row(row):
    """Converts a Psycopg DictRow into a plain dict."""
    return dict(row)

def create_jwt_token(user_id):
    """Creates a 24-hour JWT token for the user."""
    payload = {
        'sub': user_id,
        'iat': datetime.now(timezone.utc),
        'exp': datetime.now(timezone.utc) + timedelta(hours=24)
    }
    token = jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')
    return token

def get_user_id_from_token():
    """
    Protected function. Checks the Authorization header for a valid JWT
    and returns the user_id if valid.
    """
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return None, (jsonify({"error": "Missing authorization token"}), 401)
        
    try:
        token_type, token = auth_header.split(' ')
        if token_type.lower() != 'bearer':
            raise ValueError("Invalid token type")
            
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        user_id = payload['sub']
        return user_id, None
    except jwt.ExpiredSignatureError:
        return None, (jsonify({"error": "Token has expired"}), 401)
    except Exception as e:
        return None, (jsonify({"error": f"Invalid token: {str(e)}"}), 401)

# --- 3. AUTHENTICATION API ENDPOINTS ---

@app.route('/api/login')
def login():
    redirect_uri = url_for('auth_callback', _external=True)
    session['nonce'] = secrets.token_urlsafe(16)
    return google.authorize_redirect(redirect_uri, nonce=session['nonce'])

@app.route('/auth/callback')
def auth_callback():
    try:
        token = google.authorize_access_token()
        nonce = session.pop('nonce', None)
        user_info = google.parse_id_token(token, nonce=nonce)
        user_id = user_info['email']

        if not user_id:
            return redirect(f"{FRONTEND_URL}?error=Login failed")

        conn = get_db()
        database.get_or_create_user(conn, user_id)
        conn.close()

        app_token = create_jwt_token(user_id)
        return redirect(f"{FRONTEND_URL}?token={app_token}")

    except Exception as e:
        return redirect(f"{FRONTEND_URL}?error=AuthCallbackError: {str(e)}")

@app.route('/api/me')
def get_me():
    user_id, error = get_user_id_from_token()
    if error: return error
    return jsonify({"user_id": user_id})

# --- 4. SECURE API ENDPOINTS ---

@app.route('/api/settings', methods=['GET'])
def get_settings():
    user_id, error = get_user_id_from_token()
    if error: return error
    
    conn = get_db()
    settings = database.get_settings(conn, user_id)
    conn.close()
    if settings:
        return jsonify(settings)
    return jsonify({"error": "Settings not found"}), 404

@app.route('/api/settings', methods=['POST'])
def update_settings():
    user_id, error = get_user_id_from_token()
    if error: return error
    
    data = request.json
    try:
        conn = get_db()
        database.update_settings(conn, user_id, data['start_balance'], data['start_date'])
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/calendar_data', methods=['GET'])
def get_calendar_data():
    user_id, error = get_user_id_from_token()
    if error: return error
    
    start_date = request.args.get('start')
    end_date = request.args.get('end')
    
    if not start_date or not end_date:
        return jsonify({"error": "start and end parameters are required"}), 400
        
    try:
        conn = get_db()
        projection_end_date = (datetime.strptime(end_date, "%Y-%m-%d") + relativedelta(years=2)).isoformat()
        engine.run_projection(conn, user_id, projection_end_date)
        
        df = engine.get_calendar_data(conn, user_id, start_date, end_date)
        conn.close()
        
        # --- FIX FOR 500 ERROR ---
        if df.empty:
            return jsonify([]) # Return an empty list if no data
        # --- END FIX ---
            
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
        return jsonify(df.to_dict('records'))
        
    except Exception as e:
        return jsonify({"error": f"Error in get_calendar_data: {str(e)}"}), 500

# --- TRANSACTION ENDPOINTS ---

@app.route('/api/transaction/<int:transaction_id>', methods=['GET'])
def get_transaction(transaction_id):
    user_id, error = get_user_id_from_token()
    if error: return error
    
    try:
        conn = get_db()
        transaction = database.get_transaction(conn, user_id, transaction_id)
        conn.close()
        if transaction:
            return jsonify(serialize_row(transaction))
        return jsonify({"error": "Transaction not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/transactions/<date>', methods=['GET'])
def get_transactions_for_day(date):
    user_id, error = get_user_id_from_token()
    if error: return error
    
    try:
        conn = get_db()
        transactions = database.get_transactions_for_day(conn, user_id, date)
        conn.close()
        return jsonify([serialize_row(tx) for tx in transactions])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/transactions', methods=['POST'])
def add_transaction():
    user_id, error = get_user_id_from_token()
    if error: return error
    
    data = request.json
    try:
        conn = get_db()
        database.add_transaction(
            conn, user_id,
            data['date'],
            data.get('category_id'),
            data.get('description'),
            data['amount'],
            data['is_confirmed']
        )
        conn.close()
        return jsonify({"status": "success", "message": "Transaction added"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/transactions/<int:transaction_id>', methods=['PUT'])
def update_transaction(transaction_id):
    user_id, error = get_user_id_from_token()
    if error: return error
    
    data = request.json
    try:
        conn = get_db()
        database.update_transaction(
            conn, user_id, transaction_id,
            data['date'],
            data.get('category_id'),
            data.get('description'),
            data['amount'],
            data['is_confirmed']
        )
        conn.close()
        return jsonify({"status": "success", "message": "Transaction updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/transactions/<int:transaction_id>', methods=['DELETE'])
def delete_transaction(transaction_id):
    user_id, error = get_user_id_from_token()
    if error: return error
    
    try:
        conn = get_db()
        database.delete_transaction(conn, user_id, transaction_id)
        conn.close()
        return jsonify({"status": "success", "message": "Transaction deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- SCHEDULE ENDPOINTS ---

@app.route('/api/schedules', methods=['GET'])
def get_schedules():
    user_id, error = get_user_id_from_token()
    if error: return error
    
    try:
        conn = get_db()
        schedules = database.get_scheduled_transactions(conn, user_id)
        conn.close()
        return jsonify([serialize_row(s) for s in schedules])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/schedules', methods=['POST'])
def add_schedule():
    user_id, error = get_user_id_from_token()
    if error: return error
    
    data = request.json
    try:
        conn = get_db()
        database.add_scheduled_transaction(
            conn, user_id,
            data.get('category_id'),
            data.get('description'),
            data['amount'],
            data['frequency'],
            data['start_date'],
            data.get('end_date')
        )
        conn.close()
        return jsonify({"status": "success", "message": "Schedule added"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/schedules/<int:schedule_id>', methods=['DELETE'])
def delete_schedule(schedule_id):
    user_id, error = get_user_id_from_token()
    if error: return error
    
    delete_future = request.args.get('delete_future', 'true').lower() == 'true'
    try:
        conn = get_db()
        database.delete_scheduled_transaction(conn, user_id, schedule_id, delete_future)
        conn.close()
        return jsonify({"status": "success", "message": "Schedule deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- CATEGORY ENDPOINTS ---

@app.route('/api/categories', methods=['GET'])
def get_categories():
    user_id, error = get_user_id_from_token()
    if error: return error
    
    try:
        conn = get_db()
        categories = database.get_categories(conn, user_id)
        conn.close()
        return jsonify([serialize_row(c) for c in categories])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/categories', methods=['POST'])
def add_category():
    user_id, error = get_user_id_from_token()
    if error: return error
    
    data = request.json
    try:
        conn = get_db()
        new_id = database.add_category(conn, user_id, data['name'], data['type'])
        conn.close()
        return jsonify({"status": "success", "message": "Category added", "new_id": new_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/categories/<int:category_id>', methods=['PUT'])
def update_category(category_id):
    user_id, error = get_user_id_from_token()
    if error: return error

    data = request.json
    try:
        conn = get_db()
        database.update_category(conn, user_id, category_id, data['name'], data['type'])
        conn.close()
        return jsonify({"status": "success", "message": "Category updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
        
@app.route('/api/categories/<int:category_id>', methods=['DELETE'])
def delete_category(category_id):
    user_id, error = get_user_id_from_token()
    if error: return error
    
    try:
        conn = get_db()
        database.delete_category(conn, user_id, category_id)
        conn.close()
        return jsonify({"status": "success", "message": "Category deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- 5. RUN THE APP ---
if __name__ == '__main__':
    try:
        print("Initializing database...")
        conn = database.initialize_database()
        conn.close()
        print("Initialization complete.")
    except Exception as e:
        print(f"Error during startup: {e}")

    print("\n" + "="*50)
    print("🚀 Flask server is starting for LOCAL DEVELOPMENT...")
    print(f"Your frontend should be running at: {FRONTEND_URL}")
    print("This server is running at: http://127.0.0.1:5000")
    print("="*50 + "\n")
    app.run(debug=False, port=5000)
