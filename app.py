
import os
import sqlite3
import pandas as pd
from flask import Flask, jsonify, request, redirect, url_for, session
from flask_cors import CORS
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
from authlib.integrations.flask_client import OAuth
import jwt

# Import our custom modules
import database
import engine

# --- 1. APP & DB INITIALIZATION ---
app = Flask(__name__)

# --- Load Config from Environment Variables ---
# We use os.environ.get() to read the secrets
# In production (Render), these are set in the Render dashboard.
# For local testing, you would set these in your terminal.
app.config['SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'default-super-secret-key-for-local-dev')
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')
# This is the URL of our *frontend* (Netlify or local HTML file)
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://127.0.0.1:5500')

# Enable CORS to allow our frontend to make requests
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

def serialize_row(row, cursor):
    """Converts a database row (tuple) into a JSON-friendly dict."""
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))

def create_jwt_token(user_id):
    """Creates a 24-hour JWT token for the user."""
    payload = {
        'sub': user_id, # 'sub' is standard for "subject"
        'iat': datetime.now(timezone.utc), # 'iat' is "issued at"
        'exp': datetime.now(timezone.utc) + timedelta(hours=24) # 'exp' is "expiration"
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
        # Header should be "Bearer <token>"
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
    """
    Step 1. Redirects the user to Google's login page.
    """
    # Get the redirect URI for our *own* /auth/callback endpoint
    redirect_uri = url_for('auth_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def auth_callback():
    """
    Step 2. Google redirects here after login.
    We exchange Google's code for a user token, create our *own* JWT,
    and redirect the user back to the frontend with the JWT.
    """
    try:
        # Get the user's info from Google
        token = google.authorize_access_token()
        user_info = google.get('openid/userinfo').json()
        user_id = user_info['email'] # user_id is their email

        if not user_id:
            return redirect(f"{FRONTEND_URL}?error=Login failed")

        # Create the user in our database if they don't exist
        conn = get_db()
        database.get_or_create_user(conn, user_id)
        conn.close()

        # Create our own secure token (JWT)
        app_token = create_jwt_token(user_id)

        # Redirect the user back to the frontend, passing the token in the URL
        # The frontend JS will grab this, save it, and be logged in.
        return redirect(f"{FRONTEND_URL}?token={app_token}")

    except Exception as e:
        return redirect(f"{FRONTEND_URL}?error=AuthCallbackError: {str(e)}")

@app.route('/api/me')
def get_me():
    """A protected route to check if a user is logged in."""
    user_id, error = get_user_id_from_token()
    if error:
        return error
    
    return jsonify({"user_id": user_id})

# --- 4. SECURE API ENDPOINTS ---

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get the current start_balance and start_date."""
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
    """Update the start_balance and start_date."""
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
    """
    The main endpoint to get all data for the calendar view.
    Runs projection and calculates all balances.
    """
    user_id, error = get_user_id_from_token()
    if error: return error
    
    start_date = request.args.get('start')
    end_date = request.args.get('end')
    
    if not start_date or not end_date:
        return jsonify({"error": "start and end parameters are required"}), 400
        
    try:
        conn = get_db()
        # 1. Run projection for this user
        projection_end_date = (datetime.strptime(end_date, "%Y-%m-%d") + relativedelta(years=2)).isoformat()
        engine.run_projection(conn, user_id, projection_end_date)
        
        # 2. Get calculated calendar data for this user
        df = engine.get_calendar_data(conn, user_id, start_date, end_date)
        conn.close()
        
        # 3. Convert to JSON
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
        return jsonify(df.to_dict('records'))
        
    except Exception as e:
        return jsonify({"error": f"Error in get_calendar_data: {str(e)}"}), 500

# --- TRANSACTION ENDPOINTS ---

@app.route('/api/transaction/<int:transaction_id>', methods=['GET'])
def get_transaction(transaction_id):
    """Get a single transaction by its ID."""
    user_id, error = get_user_id_from_token()
    if error: return error
    
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM transactions WHERE transaction_id = ? AND user_id = ?", (transaction_id, user_id))
        transaction = c.fetchone()
        conn.close()
        if transaction:
            c_ser = database.create_connection().cursor() # Need a new cursor for description
            c_ser.execute("SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,))
            return jsonify(serialize_row(transaction, c_ser))
        return jsonify({"error": "Transaction not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/transactions/<date>', methods=['GET'])
def get_transactions_for_day(date):
    """Get all transactions for a specific day."""
    user_id, error = get_user_id_from_token()
    if error: return error
    
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT t.*, c.name, c.type 
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.category_id
            WHERE t.user_id = ? AND t.date = ?
        """, (user_id, date))
        transactions = [serialize_row(row, c) for row in c.fetchall()]
        conn.close()
        return jsonify(transactions)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/transactions', methods=['POST'])
def add_transaction():
    """Add a new one-time transaction."""
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
    """Update an existing transaction."""
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
    """Delete a single transaction."""
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
    """Get all scheduled transaction rules."""
    user_id, error = get_user_id_from_token()
    if error: return error
    
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT s.*, c.name, c.type 
            FROM scheduled_transactions s
            LEFT JOIN categories c ON s.category_id = c.category_id
            WHERE s.user_id = ?
        """, (user_id,))
        schedules = [serialize_row(row, c) for row in c.fetchall()]
        conn.close()
        return jsonify(schedules)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/schedules', methods=['POST'])
def add_schedule():
    """Add a new scheduled transaction rule."""
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
    """Delete a scheduled transaction rule."""
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
    """Get all categories."""
    user_id, error = get_user_id_from_token()
    if error: return error
    
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM categories WHERE user_id = ? ORDER BY name", (user_id,))
        categories = [serialize_row(row, c) for row in c.fetchall()]
        conn.close()
        return jsonify(categories)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/categories', methods=['POST'])
def add_category():
    """Add a new category."""
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
    """Update an existing category."""
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
    """Delete a category."""
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
    # This is used for local development
    # In production, gunicorn runs the 'app' variable directly
    print("\n" + "="*50)
    print("🚀 Flask server is starting for LOCAL DEVELOPMENT...")
    print("It's using secrets from your local environment.")
    print("Open your index.html file (or http://127.0.0.1:5500) to view the app.")
    print("="*50 + "\n")
    app.run(debug=True, port=5000)
