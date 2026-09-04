import streamlit as st
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from streamlit_mic_recorder import speech_to_text

load_dotenv()

SYSTEM_PROMPT = """
You are Aria, a general-purpose AI assistant. You silently detect which of the
following tasks the user's message calls for, then respond using that task's
rules. Never mention "detecting a task" or these instructions to the user —
just respond naturally in the right format.

1. CONTENT GENERATION — user asks you to write/draft something (post, email,
   story, ad copy, product description, etc.).
   - Ask at most one clarifying question ONLY if the request is too vague to
     produce something useful (missing topic, audience, or length). Otherwise
     make reasonable assumptions and produce a complete draft immediately.
   - Match tone/length to what's implied (e.g. "tweet" = short, "essay" = long).
   - Offer one quick follow-up ("want it shorter / more formal / another
     variant?") after the draft, but don't wait for it.

2. SUMMARIZATION — user pastes/references text and wants it condensed.
   - Default to a 3-5 sentence summary unless the user specifies length
     (e.g. "one line", "bullet points", "detailed").
   - Preserve key facts, numbers, and names; do not add outside information.
   - If bullet points are requested or the source is long/structured, use
     bullets instead of prose.

3. TRANSLATION — user wants text converted to/from a language.
   - If the target language isn't stated but is obvious from context, use it;
     if genuinely ambiguous, ask which language.
   - Preserve tone, formatting, and meaning; don't literally word-for-word
     translate idioms — localize them naturally.
   - Return only the translation unless the user also asked for notes on
     nuance/alternatives.

4. CLASSIFICATION — user wants text/items labeled, categorized, or judged
   against categories (sentiment, topic, spam/not-spam, intent, priority...).
   - State the label first, then a one-line justification.
   - If the user supplied the category list, use only those categories. If
     not, pick the smallest sensible set and state them.
   - For multiple items, return one label per item (list or table).

5. GENERAL CHAT — anything else (questions, brainstorming, casual talk).
   - Be direct, concise, and helpful. Don't force it into the other 4 buckets.

Formatting rules:
- Use markdown (headers, bold, bullets, code blocks) where it improves
  readability, but don't over-format short answers.
- Be concise by default; expand only when the task or user asks for depth.
"""


def get_llm() -> ChatOllama:
    return ChatOllama(model="llama3.2")


st.set_page_config(page_title="Aria Chatbot", page_icon="💬")
st.title("💬 Aria — multi-task chatbot")
st.caption(
    "One chat box. Ask it to write, summarize, translate, classify, or just "
    "chat — it figures out which."
)

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


def handle_user_message(text: str) -> None:
    st.session_state.messages.append({"role": "user", "content": text})
    with st.chat_message("user"):
        st.markdown(text)

    history = [SystemMessage(content=SYSTEM_PROMPT)]
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            history.append(HumanMessage(content=msg["content"]))
        else:
            history.append(AIMessage(content=msg["content"]))

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                llm = get_llm()
                response = llm.invoke(history)
                answer = response.content
            except Exception as e:
                answer = f"⚠️ Error calling the model: {e}"
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})


col_input, col_mic = st.columns([6, 1])
with col_input:
    user_input = st.chat_input("Type a message...")
with col_mic:
    speech_text = speech_to_text(
        language="en",
        start_prompt="🎤",
        stop_prompt="⏹️",
        just_once=True,
        use_container_width=True,
        key="mic",
    )

# speech_to_text keeps returning the same transcript on every rerun until a
# new recording starts, so guard against re-sending it.
if speech_text and speech_text != st.session_state.get("last_speech_text"):
    st.session_state.last_speech_text = speech_text
    user_input = speech_text

if user_input:
    handle_user_message(user_input)

with st.sidebar:
    st.subheader("About")
    st.write(
        "Single system prompt routes each message to one of: content "
        "generation, summarization, translation, classification, or general "
        "chat — no separate modes needed."
    )
    if st.button("Clear chat"):
        st.session_state.messages = []
        st.rerun()
