import os.path
import pickle

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- Configuration ---
# If modifying these scopes, delete the file token.json.
# 'readonly' means the script can only read/search, not send or delete.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly'] 
CREDENTIALS_FILE = 'D:\MyData\Personal\CashMate\credentials.json'
TOKEN_FILE = 'token.json'

def get_gmail_service():
    """
    Handles the authentication flow, loads or creates the token.json file,
    and returns a service object for interacting with the Gmail API.
    """
    creds = None
    
    # 1. Check for existing token (token.json)
    if os.path.exists(TOKEN_FILE):
        print(f"Loading credentials from {TOKEN_FILE}...")
        try:
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
        except Exception as e:
            print(f"Error loading {TOKEN_FILE}: {e}. Will re-authenticate.")
            creds = None
    
    # 2. Refresh or create new token
    if not creds or not creds.valid:
        # If credentials exist but are expired, try to refresh them
        if creds and creds.expired and creds.refresh_token:
            print("Credentials expired. Attempting to refresh token...")
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Token refresh failed: {e}. Starting full OAuth flow.")
                creds = None
        
        # If no credentials or refresh failed, start the full browser flow
        if not creds:
            print("Starting new OAuth authentication flow (browser will open)...")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES)
                # This opens the browser for you to log into your Gmail account
                creds = flow.run_local_server(port=0)
            except FileNotFoundError:
                print(f"\n--- FATAL ERROR: Credentials file '{CREDENTIALS_FILE}' not found. ---")
                print("Please download your OAuth 2.0 Client ID JSON and name it 'credentials.json'.")
                return None
            except Exception as e:
                print(f"\n--- FATAL ERROR: OAuth flow failed. Check your network or credentials. ---")
                print(f"Details: {e}")
                return None

        # 3. Save the new/refreshed token for next time
        print(f"Authentication successful. Saving credentials to {TOKEN_FILE}...")
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)

    # 4. Build and return the service object
    return build('gmail', 'v1', credentials=creds)


def list_inbox_messages(service):
    """
    Lists the IDs and Snippets (brief content) of the first 10 messages 
    in the user's inbox and prints them.
    
    Args:
        service: Authorized Gmail API service object.
    """
    if not service:
        print("Cannot access service. Aborting.")
        return

    try:
        # Call the API to list messages from the user's mailbox (userId='me')
        print("\n--- Fetching the first 10 message IDs from your Inbox ---")
        
        results = service.users().messages().list(
            userId='me', 
            maxResults=10, 
            labelIds=['INBOX']
        ).execute()
        
        messages = results.get('messages', [])

        if not messages:
            print('No messages found in your inbox.')
            return

        print(f"Found {len(messages)} messages (up to maxResults=10):")
        
        # Loop through each message ID and fetch the 'snippet' (a short preview)
        for i, message in enumerate(messages):
            # Fetch the message details (specifically the snippet)
            msg = service.users().messages().get(
                userId='me', 
                id=message['id'], 
                format='metadata', # Request only essential metadata for speed
                metadataHeaders=['From', 'Subject']
            ).execute()
            
            # Extract header information
            subject = next((h['value'] for h in msg['payload']['headers'] if h['name'] == 'Subject'), 'No Subject')
            sender = next((h['value'] for h in msg['payload']['headers'] if h['name'] == 'From'), 'Unknown Sender')

            print(f"[{i+1}] ID: {message['id']}")
            print(f"    From: {sender}")
            print(f"    Subject: {subject}")
            print(f"    Snippet: {msg.get('snippet', 'No snippet available')}\n")

    except HttpError as error:
        # Handle API errors (e.g., rate limits, invalid scopes)
        print(f'An API error occurred: {error}')


if __name__ == '__main__':
    # Ensure necessary libraries are installed:
    # pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
    
    # 1. Get the authenticated service object
    gmail_service = get_gmail_service()
    
    # 2. Use the service object to list emails
    if gmail_service:
        list_inbox_messages(gmail_service)

    print("\nScript finished.")