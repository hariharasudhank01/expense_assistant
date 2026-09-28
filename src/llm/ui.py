import streamlit as st
from src.llm.agent import ask

st.set_page_config(page_title="Expense Assistant", layout="centered")

st.markdown("""
<style>
    .stChatMessage { border-radius: 12px; }
    .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

st.title("Expense Assistant")
st.caption("Ask about your spending, upcoming week's balance, top merchants, or anything unusual.")

with st.sidebar:
    st.subheader("Try asking")
    st.markdown("""
- Will I have enough money this week if I have $200?
- Which category did I spend the most on last month?
- Who are my top 5 merchants?
- Any unusual transactions in July 2026?
""")
    if st.button("Clear chat"):
        st.session_state.messages = []
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if query := st.chat_input("Ask about your spending..."):
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        with st.spinner("Checking your transactions..."):
            answer = ask(query)
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
