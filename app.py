import streamlit as st
import pandas as pd
import io
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
import streamlit_authenticator as stauth
import google.generativeai as genai

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="CSADA FAQ System", page_icon="🏢", layout="wide")

# --- 1. SAFEGUARDED DRIVE & GEMINI API CONNECTION ---
@st.cache_resource
def get_drive_service():
    raw_creds = st.secrets["gcp_service_account"]
    
    # Ép kiểu dữ liệu tàn nhẫn để chặn đứng lỗi 'list indices must be integers'
    if isinstance(raw_creds, (list, tuple)):
        creds_info = raw_creds[0]
    else:
        creds_info = raw_creds
        
    creds_dict = {str(k): str(v) for k, v in creds_info.items()}
    creds = service_account.Credentials.from_service_account_info(creds_dict)
    return build('drive', 'v3', credentials=creds)

drive_service = get_drive_service()

if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# --- 2. RECURSIVE FOLDER SCANNING ---
def get_files_in_folder(folder_id):
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
        if isinstance(item, dict) and item.get('name') == 'CSADA-UserDetail':
            request = drive_service.files().export_media(
                fileId=item['id'],
                mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            file_stream = io.BytesIO(request.execute())
            return pd.read_excel(file_stream)
    return pd.DataFrame()

# --- OPTIMIZED CREDENTIALS ---
@st.cache_data(ttl=600)
def prepare_credentials(_df_users):
    creds = {"usernames": {}}
    if not _df_users.empty:
        active_users = _df_users[_df_users['AGENT_STATUS'].astype(str).str.strip().str.upper() == 'ACTIVE']
        raw_passwords = active_users['Password'].astype(str).str.strip().tolist()
        hashed_passwords = stauth.Hasher.hash_passwords(raw_passwords)
        
        for i, (_, row) in enumerate(active_users.iterrows()):
            email = str(row['MAIL']).strip()
            creds["usernames"][email] = {
                "email": email,
                "name": str(row['NAME']).strip(),
                "password": hashed_passwords[i]
            }
    return creds

# --- 4. SCAN AND CATEGORIZE FAQ DATA ---
@st.cache_data(ttl=3600)
def build_faq_catalog(root_folder_id):
    catalog = {} 
    root_items = get_files_in_folder(root_folder_id)
    faq_data_folder = next((item for item in root_items if isinstance(item, dict) and item.get('name') == 'faq_data'), None)
    
    if not faq_data_folder:
        return catalog

    lang_folders = get_files_in_folder(faq_data_folder['id'])
    for lang in lang_folders:
        if not isinstance(lang, dict): continue
        lang_name = lang.get('name')
        if not lang_name: continue
        catalog[lang_name] = {}
        
        brand_folders = get_files_in_folder(lang['id'])
        for brand in brand_folders:
            if not isinstance(brand, dict): continue
            brand_name = brand.get('name')
            if not brand_name: continue
            catalog[lang_name][brand_name] = []
            
            docs = get_files_in_folder(brand['id'])
            for doc in docs:
                if isinstance(doc, dict) and doc.get('mimeType') != 'application/vnd.google-apps.folder':
                    catalog[lang_name][brand_name].append({
                        'file_name': doc.get('name'),
                        'file_id': doc.get('id'),
                        'mime_type': doc.get('mimeType')
                    })
    return catalog

# --- 5. DATA EXTRACTION FOR AI CONTEXT ---
def extract_document_context(catalog, selected_lang, selected_client):
    """Retrieve file metadata as text context"""
    context = ""
    if selected_lang in catalog and selected_client in catalog[selected_lang]:
        files = catalog[selected_lang][selected_client]
        context += f"--- DOCUMENTS FOR {selected_client.upper()} ({selected_lang.upper()}) ---\n"
        for f in files:
            context += f"Document Title: {f['file_name']}\n"
            # Tính năng đọc sâu nội dung PDF/Excel sẽ được nối vào khối này sau khi ổn định kiến trúc
            context += f"[The content of {f['file_name']} is currently being referenced by the system.]\n"
    else:
        context = "No specific documents found for this selection."
    return context

# --- 6. GEMINI 1.5 FLASH ENGINE ---
def generate_gemini_response(query, context, client_name, region):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
        You are a strict and precise Customer Service (CS) Assistant for ADA.
        Your task is to answer inquiries regarding the Client: {client_name} in Region: {region}.
        
        STRICT RULES:
        1. YOU MUST BASE YOUR ANSWER ONLY ON THE "CONTEXT BOX" BELOW.
        2. If the context box does not contain the answer, reply strictly: "Information not found in the current {client_name} FAQ repository."
        3. Do not assume, hallucinate, or bring outside knowledge.
        
        [CONTEXT BOX START]
        {context}
        [CONTEXT BOX END]
        
        Agent Query: {query}
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI Engine Error: {e}"

# ==========================================
# MAIN INTERFACE & LOGIN FLOW
# ==========================================
ROOT_FOLDER_ID = "1ZXM5TjT2PPWAtA39ofvBGiBh5owWyuq0"

try:
    with st.spinner("Syncing authorization system..."):
        df_users = load_users(ROOT_FOLDER_ID)
        credentials = prepare_credentials(df_users)
        
    authenticator = stauth.Authenticate(
        credentials,
        "cs_faq_cookie",
        "ada_secret_key_2026",
        cookie_expiry_days=30
    )

    st.subheader('CSADA FAQ Portal Login')
    name, authentication_status, username = authenticator.login(location='main')

    if authentication_status == False:
        st.error('❌ Incorrect Email or Password. Please try again.')
    elif authentication_status == None:
        st.info('ℹ️ Please enter your internal account credentials.')
    elif authentication_status:
        # ==========================================
        # INTERACT WINDOW
        # ==========================================
        col_welcome, col_logout = st.columns([5, 1])
        with col_welcome:
            st.markdown(f"**Welcome {name}**")
        with col_logout:
            authenticator.logout('Logout', 'main')
            
        st.divider()
        
        with st.spinner("Syncing FAQ document repository..."):
            faq_catalog = build_faq_catalog(ROOT_FOLDER_ID)
            
        if not faq_catalog:
            st.warning("No FAQ data found in the Google Drive folder.")
        else:
            available_languages = list(faq_catalog.keys())
            
            with st.sidebar:
                st.write("### Settings")
                selected_lang = st.selectbox("Language / Region", available_languages)
                
            st.write("**:speech_balloon: Conversation:**")
            chat_container = st.container(height=400, border=True)
            
            available_brands = list(faq_catalog[selected_lang].keys()) if selected_lang in faq_catalog else []
            col_client, col_brand = st.columns(2)
            with col_client:
                selected_client = st.selectbox("Client", available_brands)
            with col_brand:
                st.selectbox("Store", ["All Stores"]) 
            
            # Làm sạch Session State để chống lỗi ép kiểu dữ liệu chuỗi    
            if 'messages' not in st.session_state:
                st.session_state.messages = []
            else:
                st.session_state.messages = [m for m in st.session_state.messages if isinstance(m, dict)]

            with chat_container:
                for message in st.session_state.messages:
                    with st.chat_message(message.get("role", "unknown")):
                        st.markdown(message.get("content", ""))

            if prompt := st.chat_input("Enter your FAQ query here..."):
                with chat_container:
                    with st.chat_message("user"):
                        st.markdown(prompt)
                st.session_state.messages.append({"role": "user", "content": prompt})

                with chat_container:
                    with st.chat_message("assistant"):
                        message_placeholder = st.empty()
                        message_placeholder.markdown(f"Generating context for **{selected_client}**... ⏳")
                        
                        document_context = extract_document_context(faq_catalog, selected_lang, selected_client)
                        
                        if "GEMINI_API_KEY" not in st.secrets:
                            response_text = "System alert: GEMINI_API_KEY is missing in Streamlit Secrets."
                        else:
                            message_placeholder.markdown("AI is processing the query... 🧠")
                            response_text = generate_gemini_response(prompt, document_context, selected_client, selected_lang)
                        
                        message_placeholder.markdown(response_text)
                        
                st.session_state.messages.append({"role": "assistant", "content": response_text})

except Exception as e:
    st.error(f"Critical System Error: {e}")
