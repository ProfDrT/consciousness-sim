import json
from datetime import timedelta

import streamlit as st
from logzero import logger
from pydantic import BaseModel, TypeAdapter
from pydantic.v1 import BaseSettings

from local_utils.session_data import BaseSessionData
from local_utils.settings import StreamlitAppSettings
from local_utils.v2.thoughts import Thought, ThoughtMemory


def check_or_x(value: bool) -> str:
    return "✅" if value else "❌"


@st.cache_resource
def setup_memory() -> ThoughtMemory:
    settings = StreamlitAppSettings.load()
    return ThoughtMemory(table_name=settings.dynamodb_thoughts_table)


@st.cache_data(ttl=timedelta(seconds=5))
def _list_recent_thoughts(num: int) -> list[dict]:
    logger.info("Getting recent thoughts from memory")
    thoughts = setup_memory().list_recently_completed_thoughts(num)
    return [x.model_dump() for x in thoughts]


def list_recent_thoughts(num=25) -> list[Thought]:
    ta = TypeAdapter(list[Thought])
    return ta.validate_python(_list_recent_thoughts(num))


@st.cache_data(ttl=timedelta(seconds=5))
def _list_incomplete_thoughts() -> list[dict]:
    logger.info("Getting incomplete thoughts from memory")
    thoughts = setup_memory().list_incomplete_thoughts()
    return [x.model_dump() for x in thoughts]


def list_incomplete_thoughts() -> list[Thought]:
    ta = TypeAdapter(list[Thought])
    return ta.validate_python(_list_incomplete_thoughts())


def dump_model(obj: BaseModel | BaseSettings) -> str:
    obj.model_dump_json()
    return json.dumps(json.loads(obj.model_dump_json()), indent=2, sort_keys=True)


def create_tabs(idx: int):
    c = st.container()
    with c:
        return


def force_home_tab():
    st.session_state["debug-bn"] = st.session_state.get("debug-bn", 0) + 1


def home_tab_hack():
    idx = st.session_state.get("debug-bn", 0)

    for x in range(idx):
        st.empty()


def render_tabbar():
    home_tab_hack()
    return st.tabs(["Home", "AI Generated Blog", "Recent Thoughts", "Debug"])


def render_debug_tab(session: BaseSessionData, settings: BaseSettings):
    with st.expander("Settings"):
        st.code(dump_model(settings))
    with st.expander("Session", expanded=True):
        st.button("Clear session data", on_click=session.clear_session, args=[session])
        st.code(dump_model(session))
        st.code(st.session_state)
    if st.toggle("Show incomplete thoughts"):
        c1, c2 = st.columns((3, 1))
        with c2:
            form = st.form("Load incomplete")
        with form:
            st.write("Load an incomplete thought")
            st.warning("This can cause issues if multiple users or tabs have the same thought processing!")
            load_incomplete = st.text_input("Thought ID")
            submitted = st.form_submit_button("Load")

        with c1:
            st.dataframe([x.model_dump() for x in list_incomplete_thoughts()])
        if submitted:
            if not load_incomplete:
                form.error("Specify thought ID")
            else:
                session.clear_session()
                session.thought_id = load_incomplete
                force_home_tab()
                st.experimental_rerun()