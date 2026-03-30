import streamlit as st
import google.generativeai as genai
from vector_engine import get_vector_db

def generate_rag_response(query, client_name, region):
    """
    Truy xuất Vector DB để lấy ngữ cảnh và gọi Gemini trả lời.
    """
    try:
        # 1. Gọi DB từ bộ nhớ local
        vector_db = get_vector_db()
        if not vector_db:
            return "Hệ thống chưa được nạp dữ liệu. Vui lòng yêu cầu Admin đồng bộ hóa tài liệu."

        # 2. Bộ lọc Metadata sống còn (Ngăn chặn trộn lẫn dữ liệu giữa các Brand)
        # Chỉ tìm kiếm trong các đoạn text có tag client và region khớp với UI
        search_kwargs = {
            "k": 5, # Lấy 5 đoạn văn bản có độ tương đồng cao nhất
            "filter": {
                "$and": [
                    {"client": {"$eq": client_name}},
                    {"region": {"$eq": region}}
                ]
            }
        }
        
        # 3. Lục soát cơ sở dữ liệu
        retriever = vector_db.as_retriever(search_kwargs=search_kwargs)
        docs = retriever.invoke(query)
        
        if not docs:
            return f"Không tìm thấy thông tin nào liên quan đến '{query}' trong tài liệu của {client_name} ({region})."

        # 4. Đóng gói 5 đoạn văn bản đó thành một Hộp Ngữ Cảnh (Context Box)
        # Ghi rõ nguồn gốc từng đoạn để nhân viên CS có thể đối chiếu nếu cần
        context = "\n\n".join([f">> Trích từ tài liệu: {doc.metadata.get('source', 'Unknown')}\n{doc.page_content}" for doc in docs])

        # 5. Triệu hồi Gemini 1.5 Flash
        if "GEMINI_API_KEY" not in st.secrets:
            return "Cảnh báo an ninh: Không tìm thấy khóa giao tiếp GEMINI_API_KEY."
            
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('gemini-2.5-flash')
        
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
        return f"Lỗi truy xuất RAG Engine: {e}"
