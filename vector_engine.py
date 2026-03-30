import streamlit as st
import os
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma

# Đường dẫn lưu trữ Vector DB cục bộ trên máy chủ Streamlit
CHROMA_PERSIST_DIR = "./chroma_db"

def get_embedding_model():
    """Khởi tạo mô hình nhúng (Embedding) của Google để biến chữ thành ma trận số"""
    if "GEMINI_API_KEY" not in st.secrets:
        raise ValueError("Thiếu GEMINI_API_KEY trong cấu hình Secrets.")
    
    return GoogleGenerativeAIEmbeddings(
        model="models/embedding-001", 
        google_api_key=st.secrets["GEMINI_API_KEY"]
    )

def build_vector_database(raw_documents):
    """
    Băm nhỏ văn bản và ép vào CSDL Vector (ChromaDB)
    raw_documents là mảng output từ file data_ingestion.py
    """
    if not raw_documents:
        print("Cảnh báo: Không có tài liệu nào để Vector hóa.")
        return None

    # 1. Kỹ thuật băm nhỏ có chồng lấp (Chunking with Overlap)
    # chunk_size: Số lượng ký tự tối đa cho mỗi mảnh
    # chunk_overlap: Số lượng ký tự vay mượn từ mảnh trước đó để giữ ngữ cảnh
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " ", ""]
    )

    chunks = []
    metadatas = []

    for doc in raw_documents:
        text = doc.get("text", "")
        metadata = doc.get("metadata", {})
        
        if text:
            # Tách 1 văn bản dài thành nhiều mảnh nhỏ
            split_texts = text_splitter.split_text(text)
            chunks.extend(split_texts)
            # Nhân bản siêu dữ liệu (Metadata) cho từng mảnh tương ứng
            metadatas.extend([metadata] * len(split_texts))

    if not chunks:
        print("Lỗi: Không thể trích xuất đoạn văn bản nào sau khi Chunking.")
        return None

    # 2. Khởi tạo Embedding Model và nạp vào ChromaDB
    embeddings = get_embedding_model()
    
    # Tạo mới hoặc ghi đè DB hiện tại
    vector_db = Chroma.from_texts(
        texts=chunks,
        embedding=embeddings,
        metadatas=metadatas,
        persist_directory=CHROMA_PERSIST_DIR
    )
    
    # Ép ChromaDB lưu dữ liệu vật lý xuống ổ cứng tạm của Streamlit
    vector_db.persist()
    print(f"Đã Vector hóa thành công {len(chunks)} phân đoạn tài liệu.")
    
    return vector_db

def get_vector_db():
    """Hàm gọi lại DB đã tồn tại để thực hiện tìm kiếm mà không cần build lại"""
    if not os.path.exists(CHROMA_PERSIST_DIR):
        return None
    
    embeddings = get_embedding_model()
    return Chroma(
        persist_directory=CHROMA_PERSIST_DIR, 
        embedding_function=embeddings
    )
