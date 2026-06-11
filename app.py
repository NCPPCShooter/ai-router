import streamlit as st
import sys
import os
from datetime import datetime

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

# ── Prompt loader ──────────────────────────────────────────
def load_prompt(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read().replace("###END###", "").strip()
    except FileNotFoundError:
        return f"Prompt file not found: {filepath}"

PROMPT_DIR = r"C:\Users\kirkk\Projects\Job-Search-Prompts\searches"

QUICK_PROMPTS = {
    "🔍 Job Search (US)": load_prompt(os.path.join(PROMPT_DIR, "sr-sourcing-manager-prompt.txt")),
    "🌍 Job Search (Global)": load_prompt(os.path.join(PROMPT_DIR, "sr-sourcing-manager-global-prompt.txt")),
    "📋 Recruiter Research": load_prompt(os.path.join(PROMPT_DIR, "recruiter-contact-search-prompt.txt")),
}

# ── Session state ──────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = []
if "result" not in st.session_state:
    st.session_state.result = None
if "route" not in st.session_state:
    st.session_state.route = None
if "pending_input" not in st.session_state:
    st.session_state.pending_input = None
if "loaded_prompt" not in st.session_state:
    st.session_state.loaded_prompt = ""

# ── Header ─────────────────────────────────────────────────
st.markdown('<div class="main-header">🤖 AI Router</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Intelligent task routing across Claude, Grok, OpenAI, GitHub Models & Perplexity</div>', unsafe_allow_html=True)

# ── Layout ─────────────────────────────────────────────────
col1, col2 = st.columns([2, 1])

with col2:
    st.subheader("Quick Prompts")
    for label, prompt in QUICK_PROMPTS.items():
        if st.button(label, use_container_width=True):
            st.session_state.loaded_prompt = prompt
            st.rerun()

    st.divider()
    st.subheader("History")
    if not st.session_state.history:
        st.caption("No tasks run yet this session.")
    else:
        for item in st.session_state.history[:10]:
            color = ROUTE_COLORS.get(item["route"], "#666")
            with st.expander(f"{item['timestamp']} · {item['route'].upper()} · {item['preview']}"):
                st.markdown(item["result"])

    st.divider()
    st.subheader("Route Guide")
    routes = [
        ("🟠 CLAUDE",   "Reasoning, writing, analysis"),
        ("🔵 GROK",     "Live job searches"),
        ("🟢 OPENAI",   "General knowledge, creative"),
        ("⚫ GITHUB",   "Code generation, debugging"),
        ("🟣 RESEARCH", "Contact & business research"),
        ("🔷 MULTI",    "Full job search pipeline"),
    ]
    for route, desc in routes:
        st.caption(f"**{route}** — {desc}")

with col1:
    st.subheader("Your Task")

    user_input = st.text_area(
        label="task",
        height=250,
        value=st.session_state.loaded_prompt,
        placeholder="Type your task here, or click a Quick Prompt button...\n\nExamples:\n• Search for remote Senior Sourcing Manager jobs paying $150K+\n• Write a Python function that...\n• Research contact info for [company]\n• What are the latest AI news stories?",
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
        st.session_state.loaded_prompt = ""
        st.session_state.pending_input = None
        st.rerun()

    if submit and user_input.strip():
        st.session_state.pending_input = user_input.replace("###END###", "").strip()
        st.session_state.loaded_prompt = ""

    if st.session_state.pending_input:
        clean_input = st.session_state.pending_input
        st.session_state.pending_input = None

        with st.spinner("Routing your task..."):
            try:
                from router import route_task, run_task

                route = route_task(clean_input)
                st.session_state.route = route

                with st.spinner(f"Running with {route.upper()}..."):
                    result = run_task(route, clean_input)
                    st.session_state.result = result

                st.session_state.history.insert(0, {
                    "timestamp": datetime.now().strftime("%b %d %I:%M %p"),
                    "route": route,
                    "preview": clean_input[:60] + "..." if len(clean_input) > 60 else clean_input,
                    "result": result
                })

            except Exception as e:
                st.session_state.result = f"Error: {str(e)}"
                st.session_state.route = "error"

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

        st.download_button(
            label="📥 Download Result",
            data=st.session_state.result,
            file_name=f"ai_router_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain"
        )