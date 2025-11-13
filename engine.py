
## /content/CashCalendarAPI/engine.py
## (Please replace the entire contents of your file with this)

import pandas as pd
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import database

def run_projection(conn, user_id, projection_end_date_str):
    """
    Generates all missing future transactions for a specific user
    up to the projection_end_date.
    """
    schedules = database.get_scheduled_transactions(conn, user_id)
    projection_end_date = datetime.strptime(projection_end_date_str, "%Y-%m-%d").date()

    for schedule in schedules:
        # Unpack all relevant fields from the tuple
        schedule_id = schedule[0]
        category_id = schedule[2]
        description = schedule[3]
        amount = schedule[4]
        frequency = schedule[5]
        start_date_str = schedule[6]
        end_date_str = schedule[7]

        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()

        # Find the last date this was generated, or use the start date
        last_gen_date_str = database.get_last_generated_date(conn, user_id, schedule_id)

        current_date = start_date
        if last_gen_date_str:
            # If it has been generated before, start from the *next* scheduled date
            last_gen_date = datetime.strptime(last_gen_date_str, "%Y-%m-%d").date()
            current_date = last_gen_date
            if frequency == 'daily':
                current_date += relativedelta(days=1)
            elif frequency == 'weekly':
                current_date += relativedelta(weeks=1)
            elif frequency == 'bi-weekly':
                current_date += relativedelta(weeks=2)
            elif frequency == 'monthly':
                current_date += relativedelta(months=1)
            elif frequency == 'bi-monthly':
                current_date += relativedelta(months=2) # Assuming every 2 months

        # Set the loop's end date
        loop_end_date = projection_end_date
        if end_date_str:
            rule_end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            if rule_end_date < projection_end_date:
                loop_end_date = rule_end_date

        # Loop and generate missing transactions
        while current_date <= loop_end_date:
            if current_date >= start_date:
                database.add_transaction(
                    conn=conn,
                    user_id=user_id,
                    date=current_date.isoformat(),
                    category_id=category_id,
                    description=description,
                    amount=amount,
                    is_confirmed=0, # 0 = Estimated
                    schedule_id=schedule_id
                )

            # Increment to the next date
            if frequency == 'daily':
                current_date += relativedelta(days=1)
            elif frequency == 'weekly':
                current_date += relativedelta(weeks=1)
            elif frequency == 'bi-weekly':
                current_date += relativedelta(weeks=2)
            elif frequency == 'monthly':
                current_date += relativedelta(months=1)
            elif frequency == 'bi-monthly':
                current_date += relativedelta(months=2) # Assuming every 2 months
            else:
                break # Failsafe for unknown frequency

# ---
# --- MODIFIED/CORRECTED FUNCTION ---
# ---
def get_calendar_data(conn, user_id, view_start_date_str, view_end_date_str):
    """
    Calculates the daily balances, credits, and debits for the calendar view
    for a specific user.
    """
    settings = database.get_settings(conn, user_id)
    if not settings:
        return pd.DataFrame() # No settings, return empty

    start_balance = settings['start_balance']
    start_date_str = settings['start_date']
    start_date_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    
    view_start_dt = datetime.strptime(view_start_date_str, "%Y-%m-%d").date()
    view_end_dt = datetime.strptime(view_end_date_str, "%Y-%m-%d").date()

    # 1. Get ALL transactions from the user's global start date
    all_transactions = database.get_all_transactions_after(conn, user_id, start_date_str)

    # 2. Create a full date range for the *requested view*
    full_date_range = pd.date_range(start=view_start_dt, end=view_end_dt, freq='D')
    calendar_df = pd.DataFrame(index=full_date_range).reset_index().rename(columns={'index': 'date'})

    # 3. Create daily summary from transactions
    if all_transactions:
        df = pd.DataFrame(all_transactions, columns=[
            'transaction_id', 'user_id', 'schedule_id', 'category_id',
            'date', 'description', 'amount', 'is_confirmed', 'category_name', 'category_type'
        ])
        df['date'] = pd.to_datetime(df['date'])
        df['amount'] = pd.to_numeric(df['amount'])
        
        df['credits'] = df.apply(lambda row: row['amount'] if row['amount'] > 0 else 0, axis=1)
        df['debits'] = df.apply(lambda row: row['amount'] if row['amount'] <= 0 else 0, axis=1)
        
        daily_summary = df.groupby(pd.Grouper(key='date', freq='D')).agg(
            credits=('credits', 'sum'),
            debits=('debits', 'sum'),
            is_actual=('is_confirmed', lambda x: (x == 1).all() or x.empty)
        ).reset_index()
        daily_summary['net_change'] = daily_summary['credits'] + daily_summary['debits']
        
        # 4. Merge daily transactions onto the full calendar
        calendar_df = pd.merge(calendar_df, daily_summary, on='date', how='left')
    else:
        # No transactions, just create empty columns
        calendar_df['credits'] = 0.0
        calendar_df['debits'] = 0.0
        calendar_df['is_actual'] = True # No transactions = "actual"
        calendar_df['net_change'] = 0.0

    calendar_df = calendar_df.fillna(0) # Fill NaNs from merge or for empty
    
    # 5. Calculate the running balance *correctly*
    pd_start_date = pd.to_datetime(start_date_dt)
    
    # Get all net changes on or after the start date
    changes_after_start = calendar_df.loc[calendar_df['date'] >= pd_start_date, 'net_change']
    
    # Calculate the cumulative balance *only* for those dates
    running_balance = start_balance + changes_after_start.cumsum()
    
    # Assign this new balance to the 'balance' column
    calendar_df['balance'] = running_balance
    
    # For dates *before* the start date, fill balance with 0
    calendar_df['balance'] = calendar_df['balance'].fillna(0) 
    
    # Set 'is_actual' correctly. A day is "actual" if it's before the start date
    # OR if all its transactions (if any) are confirmed.
    calendar_df['is_actual'] = calendar_df.apply(
        lambda row: (row['date'] < pd_start_date) or (row['is_actual'] == True), 
        axis=1
    ).astype(bool)

    # 6. Return the completed DataFrame
    return calendar_df
# ---
# --- END MODIFIED FUNCTION ---
# ---
