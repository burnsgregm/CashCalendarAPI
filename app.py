
# In /CashCalendarAPI/app.py

@app.route('/auth/callback')
def auth_callback():
    try:
        token = google.authorize_access_token()
        nonce = session.pop('nonce', None)
        user_info = google.parse_id_token(token, nonce=nonce)
        user_id = user_info['email']

        if not user_id:
            return redirect(f"{FRONTEND_URL}?error=Login failed, no email found.")

        conn = get_db()
        # --- MODIFICATION ---
        # Check the return value. If it's None, creation failed.
        db_user_id = database.get_or_create_user(conn, user_id)
        conn.close()

        if db_user_id is None:
            # The database function failed and rolled back. Do not issue a token.
            print(f"Database account creation failed for {user_id}.")
            return redirect(f"{FRONTEND_URL}?error=Database account creation failed.")
        # --- END MODIFICATION ---

        app_token = create_jwt_token(db_user_id) # Use db_user_id
        return redirect(f"{FRONTEND_URL}?token={app_token}")

    except Exception as e:
        return redirect(f"{FRONTEND_URL}?error=AuthCallbackError: {str(e)}")
