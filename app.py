import streamlit as st
import pandas as pd
import io
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
import streamlit_authenticator as stauth

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="CSADA FAQ System", page_icon="🏢", layout="wide")

# --- 1. INITIALIZE DRIVE API CONNECTION ---
@st.cache_resource
def get_drive_service():
    creds_info = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(creds_info)
    return build('drive', 'v3', credentials=creds)

drive_service = get_drive_service()

# --- 2. RECURSIVE FOLDER SCANNING FUNCTION ---
def get_files_in_folder(folder_id):
    """Retrieve all files and subfolders within a folder ID"""
    query = f"'{folder_id}' in parents and trashed=false"
    results = drive_service.files().list(
        q=query, 
        fields="files(id, name, mimeType)"
    ).execute()
    return results.get('files', [])

# --- 3. READ USER DETAIL FILE ---
@st.cache_data(ttl=600)
def load_users(root_folder_id):
    items = get_files_in_folder(root_folder_id)
    for item in items:
        if item['name'] == 'CSADA-UserDetail':
            request = drive_service.files().export_media(
                fileId=item['id'],
                mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            file_stream = io.BytesIO(request.execute())
            return pd.read_excel(file_stream)
    return pd.DataFrame()

# --- OPTIMIZED CREDENTIALS PREPARATION (CACHE HASHING) ---
@st.cache_data(ttl=600)
def prepare_credentials(_df_users):
    """Process password hashing once and cache for 10 minutes"""
    creds = {"usernames": {}}
    if not _df_users.empty:
        # Filter active users
        active_users = _df_users[_df_users['AGENT_STATUS'].astype(str).str.strip().str.upper() == 'ACTIVE']
        
        # Batch hash passwords
        raw_passwords = active_users['Password'].astype(str).str.strip().tolist()
        hashed_passwords = stauth.Hasher.hash_passwords(raw_passwords)
        
        # Map into dictionary
        for i, (_, row) in enumerate(active_users.iterrows()):
            email = str(row['MAIL']).strip()
            creds["usernames"][email] = {
                "name": str(row['NAME']).strip(),
                "password": hashed_passwords[i]
            }
    return creds

# --- 4. SCAN AND CATEGORIZE FAQ DATA BY BRAND ---
@st.cache_data(ttl=3600)
def build_faq_catalog(root_folder_id):
    catalog = {} 
    root_items = get_files_in_folder(root_folder_id)
    faq_data_folder = next((item for item in root_items if item['name'] == 'faq_data'), None)
    
    if not faq_data_folder:
        return catalog

    lang_folders = get_files_in_folder(faq_data_folder['id'])
    for lang in lang_folders:
        brand_folders = get_files_in_folder(lang['id'])
        for brand in brand_folders:
            brand_name = brand['name']
            catalog[brand_name] = []
            
            docs = get_files_in_folder(brand['id'])
            for doc in docs:
                if doc['mimeType'] != 'application/vnd.google-apps.folder':
                    catalog[brand_name].append({
                        'file_name': doc['name'],
                        'file_id': doc['id'],
                        'mime_type': doc['mimeType']
                    })
    return catalog

# ==========================================
# MAIN INTERFACE & LOGIN FLOW
# ==========================================
ROOT_FOLDER_ID = "1ZXM5TjT2PPWAtA39ofvBGiBh5owWyuq0"

try:
    with st.spinner("Syncing authorization system..."):
        df_users = load_users(ROOT_FOLDER_ID)
        credentials = prepare_credentials(df_users)
        
    # 1. Initialize Authenticator
    authenticator = stauth.Authenticate(
        credentials,
        "cs_faq_cookie",
        "ada_secret_key_2026",
        cookie_expiry_days=30
    )

    # 2. Display Login Form
    st.subheader('CSADA FAQ Portal Login')
    name, authentication_status, username = authenticator.login(location='main')

    # 3. Navigation Barrier (Only allow access if True)
    if authentication_status == False:
        st.error('❌ Incorrect Email or Password. Please try again.')
    elif authentication_status == None:
        st.info('ℹ️ Please enter your internal account credentials.')
    elif authentication_status:
        # ==========================================
        # INTERACT WINDOW (Only rendered upon successful login)
        # ==========================================
        col1, col2 = st.columns([5, 1])
        with col1:
            st.success(f"Login successful! Welcome **{name}**.")
        with col2:
            authenticator.logout('Logout', 'main')
            
        st.divider()
        
        with st.spinner("Syncing FAQ document repository..."):
            faq_catalog = build_faq_catalog(ROOT_FOLDER_ID)
            
        if not faq_catalog:
            st.warning("No FAQ data found in the Google Drive folder.")
        else:
            # Dropdown chọn Brand / Store
            col_brand, col_store = st.columns(2)
            with col_brand:
                selected_brand = st.selectbox("Brand:", list(faq_catalog.keys()))
            with col_store:
                st.selectbox("Store:", ["All Stores"])
            
            # Manage Chat State
            if 'messages' not in st.session_state:
                st.session_state.messages = []

            st.write("**:speech_balloon: Conversation:**")
            chat_container = st.container(height=400, border=True)
            
            # Render lịch sử tin nhắn
            with chat_container:
                for message in st.session_state.messages:
                    with st.chat_message(message["role"]):
                        st.markdown(message["content"])

            # Khung nhập liệu (Chat Input)
            if prompt := st.chat_input("**:question: Enter your FAQ query here...**"):
                # Render câu hỏi
                with chat_container:
                    with st.chat_message("user"):
                        st.markdown(prompt)
                st.session_state.messages.append({"role": "user", "content": prompt})

                # Render luồng AI xử lý (Sẽ kết nối Gemini ở bước sau)
                with chat_container:
                    with st.chat_message("assistant"):
                        message_placeholder = st.empty()
                        message_placeholder.markdown("Searching documents... ⏳")
                        time.sleep(1.5)
                        
                        response_text = f"Received query: '{prompt}'. AI document reading feature for **{selected_brand}** will be integrated here."
                        message_placeholder.markdown(response_text)
                        
                st.session_state.messages.append({"role": "assistant", "content": response_text})

except Exception as e:
    st.error(f"System error: {e}")
