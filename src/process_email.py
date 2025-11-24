
import os.path
import pickle
import sys
from datetime import date, timedelta
import re
import sqlite3
import base64
from email.message import EmailMessage
import requests

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# --- API Configuration ---
# NOTE: The API key is left empty as required. The execution environment will provide it.
API_KEY = ""
GEMINI_MODEL = "gemini-2.5-flash-preview-09-2025"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={API_KEY}"

# --- 1. Configuration ---
# Set the desired scope to read email metadata (read-only)
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
TOKEN_FILE = 'token.json'
CREDENTIALS_FILE = 'D:/MyData/Personal/CashMate/credentials.json'

# --- NEW: User ID to SQLite Primary Key (PK) Mapping ---
# Maps the command line user ID (string) to a database primary key (integer).
USER_MAP = {
    'leila': 0,
    'brother': 1,
    'sister': 2  # Assuming 'sister' is user 2 for the db
}

DB_NAME = 'chatmate_transactions.db'
CAPITALONE_SENDER = 'capitalone@notification.capitalone.com'
CAPITALONE_SUBJECT = 'A new transaction was charged to your account'
# --- Existing Authentication Functions (Unchanged) ---
def get_token_filepath(user_id):
    """Generates a token filename specific to the user (e.g., token_leila.json)."""
    return f"token_{user_id}.json"

def get_gmail_service(user_id):
    """
    Handles the authentication flow for a specific user.
    """
    token_filepath = get_token_filepath(user_id)
    creds = None
    
    # 1. Check for existing token (user-specific token file)
    if os.path.exists(token_filepath):
        print(f"Loading credentials from {token_filepath}...")
        try:
            with open(token_filepath, 'rb') as token:
                creds = pickle.load(token)
        except Exception as e:
            print(f"Error loading {token_filepath}: {e}. Will re-authenticate.")
            creds = None
    
    # 2. Refresh or create new token
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Credentials expired. Attempting to refresh token...")
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Token refresh failed: {e}. Starting full OAuth flow.")
                creds = None
        
        if not creds:
            print(f"Starting new OAuth authentication flow for {user_id} (browser will open)...")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES)
                # This opens the browser for the user to log into their Gmail account
                creds = flow.run_local_server(port=0)
            except FileNotFoundError:
                print(f"\n--- FATAL ERROR: Credentials file '{CREDENTIALS_FILE}' not found. ---")
                return None
            except Exception as e:
                print(f"\n--- FATAL ERROR: OAuth flow failed. Check credentials or network. ---")
                print(f"Details: {e}")
                return None

        # 3. Save the new/refreshed token for next time
        print(f"Authentication successful. Saving credentials to {token_filepath}...")
        with open(token_filepath, 'wb') as token:
            pickle.dump(creds, token)

    # 4. Build and return the service object
    return build('gmail', 'v1', credentials=creds)


# --- NEW: Database Functions (Updated) ---

def initialize_db():
    """Initializes the SQLite database and creates the transactions table, including the new 'category' column."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_pk INTEGER NOT NULL,
            bank TEXT NOT NULL,
            date TEXT NOT NULL,
            vendor TEXT NOT NULL,
            dollar_amount TEXT NOT NULL,
            category TEXT NOT NULL, -- NEW COLUMN
            UNIQUE(user_pk, date, vendor, dollar_amount) 
            -- Adds a basic constraint to prevent duplicate entries
        )
    """)
    conn.commit()
    conn.close()
    print(f"Database '{DB_NAME}' initialized. Table now includes 'category'.")

def save_transaction(transaction_data):
    """Saves a single extracted transaction to the database, including the category."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO transactions (user_pk, bank, date, vendor, dollar_amount, category)
            VALUES (?, ?, ?, ?, ?, ?) -- Updated to include category
        """, (
            transaction_data['user_pk'],
            transaction_data['bank'],
            transaction_data['date'],
            transaction_data['vendor'],
            transaction_data['dollar_amount'],
            transaction_data['category'] # New value
        ))
        conn.commit()
        print(f"-> SAVED: {transaction_data['bank']} transaction for ${transaction_data['dollar_amount']} at {transaction_data['vendor']} (Category: {transaction_data['category']})")
    except sqlite3.IntegrityError:
        # This catches the UNIQUE constraint violation (duplicate transaction)
        print(f"-> SKIPPED: Duplicate transaction found for {transaction_data['vendor']} on {transaction_data['date']}")
    except Exception as e:
        print(f"-> ERROR saving transaction: {e}")
    finally:
        conn.close()


# --- Existing Email Parsing Helpers (Unchanged) ---

def get_plain_text_body(msg_part):
    """
    Extracts the plain text body from a Gmail API message payload.
    It iterates through parts and handles MIME decoding.
    """
    if 'parts' in msg_part['payload']:
        for part in msg_part['payload']['parts']:
            # Recursively check for content in sub-parts (common for multipart/alternative)
            result = get_plain_text_body(part)
            if result:
                return result
    
    # Check for text/plain mimeType
    if msg_part['mimeType'] == 'text/plain' and 'data' in msg_part['body']:
        data = msg_part['body']['data']
        # Decode base64 URL safe, then decode bytes to string
        return base64.urlsafe_b64decode(data).decode('utf-8')
        
    return None

# --- Existing Transaction Extraction Logic (Capital One) (Unchanged) ---

def extract_capitalone_transaction(plain_text, user_pk):
    """
    Uses regex to extract date, vendor, and amount from the Capital One text.
    """
    # Regex pattern to capture the required fields
    # Group 1: Date (e.g., November 21, 2025)
    # Group 2: Vendor (e.g., SUNPASS). We stop before the comma after the vendor.
    # Group 3: Amount (e.g., 10.00)
    pattern = re.compile(
        r'on\s+(.+?), at\s+(.+?),.*?amount of \$(\d+\.\d{2})',
        re.IGNORECASE | re.DOTALL
    )
    
    match = pattern.search(plain_text)
    
    if match:
        # Clean up vendor name (get everything before the comma, then strip whitespace)
        vendor_raw = match.group(2).strip()
        vendor = vendor_raw.split(',')[0].strip()
        
        transaction = {
            'user_pk': user_pk,
            'bank': 'capital_one',
            'date': match.group(1).strip(),
            'vendor': vendor,
            'dollar_amount': match.group(3).strip()
            # Category will be added by get_transaction_category()
        }
        return transaction
    
    return None

# --- NEW: Gemini Categorization Function ---

def get_transaction_category(vendor, amount):
    """
    Calls the Gemini API to categorize a transaction based on the detailed rules.
    Implements exponential backoff for retries.
    """
    max_retries = 5
    initial_delay = 1 # seconds
    
    # Construct the specific user query for this transaction
    user_query = f"Merchant: {vendor}, Amount: ${amount}"

    # Construct the payload
    payload = {
        "contents": [{ "parts": [{ "text": user_query }] }],
        "systemInstruction": { "parts": [{ "text": SYSTEM_PROMPT }] },
        # We only expect a string response, no need for grounding or tools.
    }

    print(f"-> Categorizing: {vendor} (${amount})...", end="", flush=True)

    for attempt in range(max_retries):
        try:
            response = requests.post(
                GEMINI_API_URL, 
                headers={'Content-Type': 'application/json'},
                json=payload,
                timeout=10
            )
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            result = response.json()
            
            # Extract and clean the category string
            category = result['candidates'][0]['content']['parts'][0]['text'].strip()
            
            print(f" Done. Category: {category}")
            return category

        except requests.exceptions.RequestException as e:
            # Handle connection errors, timeouts, and HTTP errors
            if attempt < max_retries - 1:
                delay = initial_delay * (2 ** attempt)
                print(f" API Error (Attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
            else:
                print(f" API Error: Maximum retries reached. Returning 'Merchandise'. Error: {e}")
                return "Merchandise" # Fallback category

    return "Merchandise" # Should be unreachable if max_retries > 0

# --- Refactored Main Processor (Updated) ---

def process_user_inbox(service, user_pk):
    """
    Searches the user's inbox for Capital One transaction emails, extracts data, 
    categorizes it using Gemini, and saves it to the database.
    
    Args:
        service: Authorized Gmail API service object.
        user_pk: The integer primary key for the user in the database.
    """
    if not service:
        print("Cannot access Gmail service. Aborting processing.")
        return

    try:
        print("\n--- Searching for Capital One Transaction Emails ---")
        
        # Construct the Gmail API query string
        query = (
            f"from:{CAPITALONE_SENDER} subject:\"{CAPITALONE_SUBJECT}\" is:unread"
        )
        
        # List messages matching the query
        results = service.users().messages().list(
            userId='me', 
            q=query
        ).execute()
        
        message_ids = results.get('messages', [])
        
        if not message_ids:
            print(f'No new Capital One transaction emails found for user PK {user_pk}.')
            return

        print(f"Found {len(message_ids)} matching emails. Processing...")
        
        
        for i, message_id_obj in enumerate(message_ids):
            message_id = message_id_obj['id']
            
            # Fetch the full message content
            full_msg = service.users().messages().get(
                userId='me', 
                id=message_id, 
                format='full' 
            ).execute()
            
            # 1. Extract the plain text body
            plain_text = get_plain_text_body(full_msg)
            
            if plain_text:
                # 2. Extract the transaction data
                transaction = extract_capitalone_transaction(plain_text, user_pk)
                
                if transaction:
                    # --- NEW STEP: Categorize the transaction using Gemini ---
                    vendor = transaction['vendor']
                    amount = transaction['dollar_amount']
                    category = get_transaction_category(vendor, amount)
                    transaction['category'] = category
                    
                    # 3. Save the data to SQLite
                    save_transaction(transaction)
                    
                    # 4. Mark the email as read after successful extraction and saving
                    service.users().messages().modify(
                        userId='me',
                        id=message_id,
                        body={'removeLabelIds': ['UNREAD']}
                    ).execute()
                else:
                    print(f"Warning: Could not extract data from message ID {message_id}. Text content not matched.")
            else:
                print(f"Warning: Could not find plain text body for message ID {message_id}.")
                
    except HttpError as error:
        print(f'An API error occurred during processing: {error}')


if __name__ == '__main__':
    # --- 1. Initialization and User Check ---
    initialize_db()
    
    if len(sys.argv) < 2:
        print("\nUSAGE ERROR: You must specify a user ID (e.g., 'leila', 'brother', 'sister').")
        print("Example: poetry run python basic_gmail_access.py leila")
        sys.exit(1)
        
    user_id = sys.argv[1]
    
    if user_id not in USER_MAP:
        print(f"\nERROR: User ID '{user_id}' is not mapped to a database primary key. Add it to USER_MAP.")
        sys.exit(1)
        
    user_pk = USER_MAP[user_id]
    print(f"\n--- Running script for user: {user_id} (PK: {user_pk}) ---")
    
    # 2. Get the authenticated service object
    gmail_service = get_gmail_service(user_id)
    
    # 3. Process the inbox
    if gmail_service:
        process_user_inbox(gmail_service, user_pk)

    print("\nScript finished.")