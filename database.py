
import sqlite3
from sqlite3 import Error
import datetime

DATABASE_NAME = "finance_db.sqlite"

def create_connection():
    """Create a database connection to the SQLite database."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON;") # Enforce foreign key constraints
    except Error as e:
        print(e)
    return conn

def create_tables(conn):
    """Create the necessary tables for the app."""
    try:
        c = conn.cursor()
        
        # --- User Table ---
        # Stores the unique Google email, which we use as the user_id
        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY
        );
        """)

        # --- User Settings ---
        # Stores the user-specific starting balance and date
        c.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id TEXT PRIMARY KEY,
            start_balance REAL NOT NULL DEFAULT 0.0,
            start_date TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        );
        """)

        # --- Categories Table ---
        # Stores user-defined categories for credits/debits
        c.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            category_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('credit', 'debit')),
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        );
        """)

        # --- Scheduled Transactions Table ---
        # Stores the RULES for recurring transactions
        c.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_transactions (
            schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            category_id INTEGER,
            description TEXT,
            amount REAL NOT NULL,
            frequency TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
            FOREIGN KEY (category_id) REFERENCES categories (category_id) ON DELETE SET NULL
        );
        """)

        # --- Transactions Table ---
        # Stores ALL individual transactions (one-time AND auto-generated)
        c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            schedule_id INTEGER,
            category_id INTEGER,
            date TEXT NOT NULL,
            description TEXT,
            amount REAL NOT NULL,
            is_confirmed INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
            FOREIGN KEY (schedule_id) REFERENCES scheduled_transactions (schedule_id) ON DELETE SET NULL,
            FOREIGN KEY (category_id) REFERENCES categories (category_id) ON DELETE SET NULL
        );
        """)
        
        conn.commit()
    except Error as e:
        print(f"Error creating tables: {e}")

def get_or_create_user(conn, user_id):
    """
    Get the user. If they don't exist, create them along with
    default settings and categories.
    """
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        
        if user is None:
            # User doesn't exist, create them
            c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
            
            # Also create their default settings
            today = datetime.date.today().isoformat()
            c.execute("""
            INSERT INTO user_settings (user_id, start_balance, start_date)
            VALUES (?, 0.0, ?)
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
            INSERT INTO categories (user_id, name, type) VALUES (?, ?, ?)
            """, default_categories)
            
            conn.commit()
            print(f"Created new user: {user_id}")
        
        return user_id
    except Error as e:
        print(f"Error in get_or_create_user: {e}")
        return None

# --- Wrapper Function ---
# This is the main function the Flask app will call
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
    c = conn.cursor()
    c.execute("SELECT * FROM categories WHERE user_id = ? ORDER BY name", (user_id,))
    return c.fetchall()

def add_category(conn, user_id, name, type):
    c = conn.cursor()
    c.execute("INSERT INTO categories (user_id, name, type) VALUES (?, ?, ?)", (user_id, name, type))
    conn.commit()
    return c.lastrowid

def update_category(conn, user_id, category_id, name, type):
    c = conn.cursor()
    c.execute("UPDATE categories SET name = ?, type = ? WHERE category_id = ? AND user_id = ?", (name, type, category_id, user_id))
    conn.commit()

def delete_category(conn, user_id, category_id):
    c = conn.cursor()
    # On delete, set foreign keys to NULL instead of deleting transactions
    c.execute("DELETE FROM categories WHERE category_id = ? AND user_id = ?", (category_id, user_id))
    conn.commit()

# --- TRANSACTION CRUD ---

def get_transaction(conn, user_id, transaction_id):
    c = conn.cursor()
    c.execute("SELECT * FROM transactions WHERE transaction_id = ? AND user_id = ?", (transaction_id, user_id))
    return c.fetchone()

def add_transaction(conn, user_id, date, category_id, description, amount, is_confirmed, schedule_id=None):
    c = conn.cursor()
    c.execute("""
    INSERT INTO transactions (user_id, date, category_id, description, amount, is_confirmed, schedule_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, date, category_id, description, amount, is_confirmed, schedule_id))
    conn.commit()
    return c.lastrowid

def update_transaction(conn, user_id, transaction_id, date, category_id, description, amount, is_confirmed):
    c = conn.cursor()
    c.execute("""
    UPDATE transactions
    SET date = ?, category_id = ?, description = ?, amount = ?, is_confirmed = ?
    WHERE transaction_id = ? AND user_id = ?
    """, (date, category_id, description, amount, is_confirmed, transaction_id, user_id))
    conn.commit()

def delete_transaction(conn, user_id, transaction_id):
    c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE transaction_id = ? AND user_id = ?", (transaction_id, user_id))
    conn.commit()
    
def get_transactions_for_day(conn, user_id, date):
    c = conn.cursor()
    c.execute("""
        SELECT t.*, c.name, c.type 
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.category_id
        WHERE t.user_id = ? AND t.date = ?
    """, (user_id, date))
    return c.fetchall()
    
def get_all_transactions_after(conn, user_id, date):
    c = conn.cursor()
    c.execute("""
        SELECT t.*, c.name, c.type 
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.category_id
        WHERE t.user_id = ? AND t.date >= ?
        ORDER BY t.date, t.transaction_id
    """, (user_id, date))
    return c.fetchall()

# --- SCHEDULED TRANSACTION CRUD ---

def add_scheduled_transaction(conn, user_id, category_id, description, amount, frequency, start_date, end_date):
    c = conn.cursor()
    c.execute("""
    INSERT INTO scheduled_transactions (user_id, category_id, description, amount, frequency, start_date, end_date)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, category_id, description, amount, frequency, start_date, end_date))
    conn.commit()
    return c.lastrowid
    
def get_scheduled_transactions(conn, user_id):
    c = conn.cursor()
    c.execute("""
        SELECT s.*, c.name, c.type 
        FROM scheduled_transactions s
        LEFT JOIN categories c ON s.category_id = c.category_id
        WHERE s.user_id = ?
    """, (user_id,))
    return c.fetchall()

def delete_scheduled_transaction(conn, user_id, schedule_id, delete_future=False):
    c = conn.cursor()
    # Delete the rule
    c.execute("DELETE FROM scheduled_transactions WHERE schedule_id = ? AND user_id = ?", (schedule_id, user_id))
    
    if delete_future:
        # Also delete all unconfirmed transactions created by this rule
        c.execute("""
        DELETE FROM transactions
        WHERE schedule_id = ? AND user_id = ? AND is_confirmed = 0
        """, (schedule_id, user_id))
    
    conn.commit()
    
def get_last_generated_date(conn, user_id, schedule_id):
    c = conn.cursor()
    c.execute("""
    SELECT MAX(date) FROM transactions
    WHERE user_id = ? AND schedule_id = ?
    """, (user_id, schedule_id))
    result = c.fetchone()[0]
    return result

# --- SETTINGS ---

def get_settings(conn, user_id):
    c = conn.cursor()
    c.execute("SELECT start_balance, start_date FROM user_settings WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    if result:
        return {"start_balance": result[0], "start_date": result[1]}
    return None

def update_settings(conn, user_id, start_balance, start_date):
    c = conn.cursor()
    c.execute("""
    UPDATE user_settings
    SET start_balance = ?, start_date = ?
    WHERE user_id = ?
    """, (start_balance, start_date, user_id))
    conn.commit()
