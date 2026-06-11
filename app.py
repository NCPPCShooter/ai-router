import streamlit as st
import sys
import os
from datetime import datetime
from io import StringIO
import threading

# Add router to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Page config
st.set_page_config(
    page_title="AI Router",
    page_icon="🤖",
    layout="wide"
)

# ── Styling ────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #2E75B6;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .route-badge {
        display: inline-block;
        padding: 0.3rem 0.8rem;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.9rem;
        margin-bottom: 1rem;
    }
    .history-item {
        padding: 0.5rem;
        border-left: 3px solid #2E75B6;
        margin-bottom: 0.5rem;
        background: #f8f9fa;
        border-radius: 0 4px 4px 0;
    }
    .stTextArea textarea {
        font-size: 0.95rem;
    }
</style>
""", unsafe_allow_html=True)

# ── Route colors ───────────────────────────────────────────
ROUTE_COLORS = {
    "claude":   "#FF6B35",
    "grok":     "#1DA1F2",
    "openai":   "#10A37F",
    "github":   "#333333",
    "research": "#7B2D8B",
    "multi":    "#2E75B6",
}

# ── Session state ──────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = []
if "result" not in st.session_state:
    st.session_state.result = None
if "route" not in st.session_state:
    st.session_state.route = None
if "processing" not in st.session_state:
    st.session_state.processing = False

# ── Header ─────────────────────────────────────────────────
st.markdown('<div class="main-header">🤖 AI Router</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Intelligent task routing across Claude, Grok, OpenAI, GitHub Models & Perplexity</div>', unsafe_allow_html=True)

# ── Layout ─────────────────────────────────────────────────
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Your Task")
    user_input = st.text_area(
        label="Enter your task or paste a prompt:",
        height=250,
        placeholder="Type your task here, or paste a saved prompt...\n\nExamples:\n• Search for remote Senior Sourcing Manager jobs paying $150K+\n• Write a Python function that...\n• Research contact info for [company]\n• What are the latest news stories about AI?",
        label_visibility="collapsed"
    )

    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 4])
    with col_btn1:
        submit = st.button("🚀 Submit", type="primary", use_container_width=True)
    with col_btn2:
        clear = st.button("🗑️ Clear", use_container_width=True)

    if clear:
        st.session_state.result = None
        st.session_state.route = None
        st.rerun()

    # ── Processing ─────────────────────────────────────────
    if submit and user_input.strip():
        # Strip ###END### if pasted from prompt file
        clean_input = user_input.replace("###END###", "").strip()

        with st.spinner("Routing your task..."):
            try:
                from router import route_task, run_task

                route = route_task(clean_input)
                st.session_state.route = route

                with st.spinner(f"Running task with {route.upper()}..."):
                    result = run_task(route, clean_input)
                    st.session_state.result = result

                # Save to history
                st.session_state.history.insert(0, {
                    "timestamp": datetime.now().strftime("%b %d %I:%M %p"),
                    "route": route,
                    "preview": clean_input[:60] + "..." if len(clean_input) > 60 else clean_input,
                    "result": result
                })

            except Exception as e:
                st.session_state.result = f"Error: {str(e)}"
                st.session_state.route = "error"

    # ── Result display ─────────────────────────────────────
    if st.session_state.result:
        route = st.session_state.route
        color = ROUTE_COLORS.get(route, "#666")

        st.markdown(f"""
        <div class="route-badge" style="background:{color}20; color:{color}; border: 1px solid {color}">
            ⚡ Routed to: {route.upper()}
        </div>
        """, unsafe_allow_html=True)

        st.subheader("Result")
        st.markdown(st.session_state.result)

        # Download button
        st.download_button(
            label="📥 Download Result",
            data=st.session_state.result,
            file_name=f"ai_router_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain"
        )

with col2:
    st.subheader("Quick Prompts")

    quick_prompts = {
        "🔍 Job Search (US)": open(r"C:\Users\kirkk\Projects\Job-Search-Prompts\searches\sr-sourcing-manager-prompt.txt").read().replace("###END###", "").strip(),
        "🌍 Job Search (Global)": open(r"C:\Users\kirkk\Projects\Job-Search-Prompts\searches\sr-sourcing-manager-global-prompt.txt").read().replace("###END###", "").strip(),
        "📋 Recruiter Research": open(r"C:\Users\kirkk\Projects\Job-Search-Prompts\searches\recruiter-contact-search-prompt.txt").read().replace("###END###", "").strip(),
    }

    for label, prompt in quick_prompts.items():
        if st.button(label, use_container_width=True):
            st.session_state["load_prompt"] = prompt
            st.rerun()

    if "load_prompt" in st.session_state:
        st.info("Prompt loaded — click Submit to run it.")

    st.divider()

    # ── History ────────────────────────────────────────────
    st.subheader("History")

    if not st.session_state.history:
        st.caption("No tasks run yet this session.")
    else:
        for i, item in enumerate(st.session_state.history[:10]):
            color = ROUTE_COLORS.get(item["route"], "#666")
            with st.expander(f"{item['timestamp']} · {item['route'].upper()} · {item['preview']}"):
                st.markdown(item["result"])

    st.divider()

    # ── Route guide ────────────────────────────────────────
    st.subheader("Route Guide")
    routes = [
        ("🟠 CLAUDE",    "Reasoning, writing, analysis"),
        ("🔵 GROK",      "Live job searches"),
        ("🟢 OPENAI",    "General knowledge, creative"),
        ("⚫ GITHUB",    "Code generation, debugging"),
        ("🟣 RESEARCH",  "Contact & business research"),
        ("🔷 MULTI",     "Full job search pipeline"),
    ]
    for route, desc in routes:
        st.caption(f"**{route}** — {desc}")