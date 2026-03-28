import streamlit as st
import pandas as pd
import io
import time
import json
import traceback
import bcrypt  # [MỚI] Bổ sung thư viện băm mật khẩu lõi
from google.oauth2 import service_account
from googleapiclient.discovery import build
import streamlit_authenticator as stauth
import google.generativeai as genai

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="CSADA FAQ System", page_icon="🏢", layout="wide")

# --- 1. BULLETPROOF DRIVE & GEMINI API CONNECTION ---
@st.cache_resource
def get_drive_service():
    raw_creds = st.secrets["gcp_service_account"]
    
    creds_info = {}
    if isinstance(raw_creds, str):
        try:
            creds_info = json.loads(raw_creds)
        except Exception:
            pass
    elif hasattr(raw_creds, "to_dict"):
        creds_info = raw_creds.to_dict()
    elif isinstance(raw_creds, list) and len(raw_creds) > 0:
        if isinstance(raw_creds[0], dict):
            creds_info = raw_creds[0]
        elif hasattr(raw_creds[0], "to_dict"):
            creds_info = raw_creds[0].to_dict()
    elif isinstance(raw_creds, dict):
        creds_info = raw_creds

    if not creds_info:
        raise ValueError("Cannot parse Google Service Account credentials from secrets.")

    creds_dict = {str(k): str(v) for k, v in creds_info.items()}
    creds = service_account.Credentials.from_service_account_info(creds_dict)
    return build('drive', 'v3', credentials=creds)

try:
    drive_service = get_drive_service()
except Exception as e:
    st.error(f"Lỗi khởi tạo Drive API: {e}")
    st.stop()

if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# --- 2. DEFENSIVE RECURSIVE FOLDER SCANNING ---
def get_files_in_folder(folder_id):
    if not folder_id or not isinstance(folder_id, str):
        return []
    try:
        query = f"'{folder_id}' in parents and trashed=false"
        results = drive_service.files().list(
            q=query, 
            fields="files(id, name, mimeType)"
        ).execute()
        
        if isinstance(results, dict):
            return results.get('files', [])
        return []
    except Exception:
        return []

# --- 3. READ USER DETAIL FILE ---
@st.cache_data(ttl=600)
def load_users(root_folder_id):
    items = get_files_in_folder(root_folder_id)
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get('name') == 'CSADA-UserDetail':
                file_id = item.get('id')
                if file_id:
                    request = drive_service.files().export_media(
                        fileId=file_id,
                        mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    )
                    file_stream = io.BytesIO(request.execute())
                    return pd.read_excel(file_stream)
    return pd.DataFrame()

# --- OPTIMIZED CREDENTIALS (SỬA LỖI HASHING) ---
@st.cache_data(ttl=600)
def prepare_credentials(_df_users):
    creds = {"usernames": {}}
    if isinstance(_df_users, pd.DataFrame) and not _df_users.empty:
        active_users = _df_users[_df_users['AGENT_STATUS'].astype(str).str.strip().str.upper() == 'ACTIVE']
        
        for i, (_, row) in enumerate(active_users.iterrows()):
            # [FIX] Cẩn trọng: Định dạng email phải trùng khớp hoàn toàn (Loại bỏ khoảng trắng thừa)
            email = str(row['MAIL']).strip()
            plain_pass = str(row['Password']).strip()
            
            # [FIX] Tự tay Hashing bằng thuật toán chuẩn thay vì phụ thuộc vào thư viện bên ngoài
            if plain_pass.startswith("$2b$"): 
                # Trường hợp password trong file Excel đã được băm sẵn
                hashed_pass = plain_pass
            else:
                # Trường hợp password trong file Excel là văn bản thuần
                hashed_pass = bcrypt.hashpw(plain_pass.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            creds["usernames"][email] = {
                "email": email,
                "name": str(row['NAME']).strip(),
                "password": hashed_pass, 
                "logged_in": False,
                "failed_login_attempts": 0
            }
            
    return creds

# --- 4. SCAN AND CATEGORIZE FAQ DATA ---
@st.cache_data(ttl=3600)
def build_faq_catalog(root_folder_id):
    catalog = {} 
    root_items = get_files_in_folder(root_folder_id)
    if not isinstance(root_items, list): return catalog
    
    faq_data_folder = next((item for item in root_items if isinstance(item, dict) and item.get('name') == 'faq_data'), None)
    if not faq_data_folder: return catalog

    lang_folders = get_files_in_folder(faq_data_folder.get('id'))
    if isinstance(lang_folders, list):
        for lang in lang_folders:
            if not isinstance(lang, dict): continue
            lang_name = lang.get('name')
            if not lang_name: continue
            catalog[lang_name] = {}
            
            brand_folders = get_files_in_folder(lang.get('id'))
            if isinstance(brand_folders, list):
                for brand in brand_folders:
                    if not isinstance(brand, dict): continue
                    brand_name = brand.get('name')
                    if not brand_name: continue
                    catalog[lang_name][brand_name] = []
                    
                    docs = get_files_in_folder(brand.get('id'))
                    if isinstance(docs, list):
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
    context = ""
    if isinstance(catalog, dict) and selected_lang in catalog:
        lang_dict = catalog.get(selected_lang, {})
        if isinstance(lang_dict, dict) and selected_client in lang_dict:
            files = lang_dict.get(selected_client, [])
            if isinstance(files, list):
                context += f"--- DOCUMENTS FOR {str(selected_client).upper()} ({str(selected_lang).upper()}) ---\n"
                for f in files:
                    if isinstance(f, dict):
                        context += f"Document Title: {f.get('file_name', 'Unknown Document')}\n"
                        context += f"[The content of {f.get('file_name')} is currently being referenced by the system.]\n"
    if not context:
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
    
    authenticator.login(location='main')
    
    authentication_status = st.session_state.get("authentication_status")
    name = st.session_state.get("name")
    username = st.session_state.get("username")

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
            
        if not faq_catalog or not isinstance(faq_catalog, dict):
            st.warning("No FAQ data found in the Google Drive folder.")
        else:
            available_languages = list(faq_catalog.keys())
            
            with st.sidebar:
                st.write("### Settings")
                selected_lang = st.selectbox("Language / Region", available_languages)
                
            st.write("**:speech_balloon: Conversation:**")
            chat_container = st.container(height=400, border=True)
            
            lang_dict = faq_catalog.get(selected_lang, {}) if isinstance(faq_catalog, dict) else {}
            available_brands = list(lang_dict.keys()) if isinstance(lang_dict, dict) else []
            
            col_client, col_brand = st.columns(2)
            with col_client:
                selected_client = st.selectbox("Client", available_brands)
            with col_brand:
                st.selectbox("Store", ["All Stores"]) 
            
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
    with st.expander("Bấm vào đây để xem chi tiết mã lỗi (Traceback)"):
        st.code(traceback.format_exc())
