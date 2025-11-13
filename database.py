
import os
import psycopg2
from psycopg2.extras import DictCursor
import datetime

DATABASE_URL = os.environ.get('DATABASE_URL')

def create_connection():
    """Create a database connection to the PostgreSQL database."""
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
    except Exception as e:
        print(f"Error connecting to database: {e}")
    return conn

def create_tables(conn):
    """Create the necessary tables for the app."""
    try:
        with conn.cursor() as c:
            # --- User Table ---
            c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY
            );
            """)

            # --- User Settings ---
            c.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY,
                start_balance REAL NOT NULL DEFAULT 0.0,
                start_date DATE NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
            """)

            # --- Categories Table ---
            c.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                category_id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('credit', 'debit')),
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
            """)

            # --- Scheduled Transactions Table ---
            c.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_transactions (
                schedule_id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                category_id INTEGER,
                description TEXT,
                amount REAL NOT NULL,
                frequency TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (category_id) REFERENCES categories (category_id) ON DELETE SET NULL
            );
            """)

            # --- Transactions Table ---
            c.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                schedule_id INTEGER,
                category_id INTEGER,
                date DATE NOT NULL,
                description TEXT,
                amount REAL NOT NULL,
                is_confirmed INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                FOREIGN KEY (schedule_id) REFERENCES scheduled_transactions (schedule_id) ON DELETE SET NULL,
                FOREIGN KEY (category_id) REFERENCES categories (category_id) ON DELETE SET NULL
            );
            """)
        
    except Exception as e:
        print(f"Error creating tables: {e}")

def get_or_create_user(conn, user_id):
    """
    Get the user. If they don't exist, create them along with
    default settings and categories.
    """
    try:
        with conn.cursor() as c:
            c.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            user = c.fetchone()
            
            if user is None:
                # User doesn't exist, create them
                c.execute("INSERT INTO users (user_id) VALUES (%s)", (user_id,))
                
                # Also create their default settings
                today = datetime.date.today().isoformat()
                c.execute("""
                INSERT INTO user_settings (user_id, start_balance, start_date)
                VALUES (%s, 0.0, %s)
                """, (user_id, today))
                
                # Create default categories
                default_categories = [
                    (user_id, 'Paycheck', 'credit'),
                    (user_id, 'Rent', 'debit'),
                    (user_id, 'Groceries', 'debit'),
                    (user_id, 'Utilities', 'debit'),
                    (user_id, 'Other', 'debit')
                ]
                c.executemany("""
                INSERT INTO categories (user_id, name, type) VALUES (%s, %s, %s)
                """, default_categories)
                
                print(f"Created new user: {user_id}")
            
            return user_id
    except Exception as e:
        print(f"Error in get_or_create_user: {e}")
        return None

# --- Wrapper Function ---
def initialize_database():
    """Initializes and returns a database connection."""
    conn = create_connection()
    if conn is not None:
        create_tables(conn)
        return conn
    else:
        raise Exception("Error! Cannot create the database connection.")

# --- CATEGORY CRUD ---

def get_categories(conn, user_id):
    with conn.cursor(cursor_factory=DictCursor) as c:
        c.execute("SELECT * FROM categories WHERE user_id = %s ORDER BY name", (user_id,))
        return c.fetchall()

def add_category(conn, user_id, name, type):
    with conn.cursor() as c:
        c.execute("INSERT INTO categories (user_id, name, type) VALUES (%s, %s, %s) RETURNING category_id", (user_id, name, type))
        return c.fetchone()[0]

def update_category(conn, user_id, category_id, name, type):
    with conn.cursor() as c:
        c.execute("UPDATE categories SET name = %s, type = %s WHERE category_id = %s AND user_id = %s", (name, type, category_id, user_id))

def delete_category(conn, user_id, category_id):
    with conn.cursor() as c:
        c.execute("DELETE FROM categories WHERE category_id = %s AND user_id = %s", (category_id, user_id))

# --- TRANSACTION CRUD ---

def get_transaction(conn, user_id, transaction_id):
    with conn.cursor(cursor_factory=DictCursor) as c:
        c.execute("SELECT * FROM transactions WHERE transaction_id = %s AND user_id = %s", (transaction_id, user_id))
        return c.fetchone()

def add_transaction(conn, user_id, date, category_id, description, amount, is_confirmed, schedule_id=None):
    with conn.cursor() as c:
        c.execute("""
        INSERT INTO transactions (user_id, date, category_id, description, amount, is_confirmed, schedule_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (user_id, date, category_id, description, amount, is_confirmed, schedule_id))

def update_transaction(conn, user_id, transaction_id, date, category_id, description, amount, is_confirmed):
    with conn.cursor() as c:
        c.execute("""
        UPDATE transactions
        SET date = %s, category_id = %s, description = %s, amount = %s, is_confirmed = %s
        WHERE transaction_id = %s AND user_id = %s
        """, (date, category_id, description, amount, is_confirmed, transaction_id, user_id))

def delete_transaction(conn, user_id, transaction_id):
    with conn.cursor() as c:
        c.execute("DELETE FROM transactions WHERE transaction_id = %s AND user_id = %s", (transaction_id, user_id))
    
def get_transactions_for_day(conn, user_id, date):
    with conn.cursor(cursor_factory=DictCursor) as c:
        c.execute("""
            SELECT t.*, c.name, c.type 
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.category_id
            WHERE t.user_id = %s AND t.date = %s
        """, (user_id, date))
        return c.fetchall()
    
def get_all_transactions_after(conn, user_id, date):
    with conn.cursor(cursor_factory=DictCursor) as c:
        c.execute("""
            SELECT t.*, c.name, c.type 
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.category_id
            WHERE t.user_id = %s AND t.date >= %s
            ORDER BY t.date, t.transaction_id
        """, (user_id, date))
        return c.fetchall()

# --- SCHEDULED TRANSACTION CRUD ---

def add_scheduled_transaction(conn, user_id, category_id, description, amount, frequency, start_date, end_date):
    with conn.cursor() as c:
        c.execute("""
        INSERT INTO scheduled_transactions (user_id, category_id, description, amount, frequency, start_date, end_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (user_id, category_id, description, amount, frequency, start_date, end_date))
    
def get_scheduled_transactions(conn, user_id):
    with conn.cursor(cursor_factory=DictCursor) as c:
        c.execute("""
            SELECT s.*, c.name, c.type 
            FROM scheduled_transactions s
            LEFT JOIN categories c ON s.category_id = c.category_id
            WHERE s.user_id = %s
        """, (user_id,))
        return c.fetchall()

def delete_scheduled_transaction(conn, user_id, schedule_id, delete_future=False):
    with conn.cursor() as c:
        c.execute("DELETE FROM scheduled_transactions WHERE schedule_id = %s AND user_id = %s", (schedule_id, user_id))
        
        if delete_future:
            c.execute("""
            DELETE FROM transactions
            WHERE schedule_id = %s AND user_id = %s AND is_confirmed = 0
            """, (schedule_id, user_id))
    
def get_last_generated_date(conn, user_id, schedule_id):
    with conn.cursor() as c:
        c.execute("""
        SELECT MAX(date) FROM transactions
        WHERE user_id = %s AND schedule_id = %s
        """, (user_id, schedule_id))
        result = c.fetchone()[0]
        return result

# --- SETTINGS ---

def get_settings(conn, user_id):
    with conn.cursor(cursor_factory=DictCursor) as c:
        c.execute("SELECT start_balance, start_date FROM user_settings WHERE user_id = %s", (user_id,))
        result = c.fetchone()
        if result:
            return {"start_balance": result[0], "start_date": result[1].isoformat()}
        return None

def update_settings(conn, user_id, start_balance, start_date):
    with conn.cursor() as c:
        c.execute("""
        UPDATE user_settings
        SET start_balance = %s, start_date = %s
        WHERE user_id = %s
        """, (start_balance, start_date, user_id))
