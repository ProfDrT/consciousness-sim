import json
import random
from pathlib import Path
from typing import Literal, Optional

import numpy as np
import streamlit as st
from logzero import logger
from PIL import Image
from pydantic import BaseModel, Field
from pydantic.v1 import BaseSettings
from wordcloud import STOPWORDS, WordCloud

from local_utils import prompts
from local_utils.brain import Brain, ReflectThoughtResponse, StartNewThoughtResponse
from local_utils.prompts import ThoughtTypes
from local_utils.session_data import BaseSessionData
from local_utils.settings import StreamlitAppSettings

st.set_page_config("Consciousness Simulator", layout="wide")


class ThoughtData(BaseSessionData):
    thought_model: str = ""
    trigger_new_thought: bool = False
    new_thought: Optional[StartNewThoughtResponse] = None
    this_thought_responses: list[ReflectThoughtResponse] = Field(default_factory=list)
    current_thought_index: int = 0
    thought_complete: bool = False
    thought_had_error: bool = False
    thought_status_msgs: list[str] = Field(default_factory=list)

    def add_reflect_thought_response(self, response: ReflectThoughtResponse):
        self.this_thought_responses.append(response)
        self.save_to_session_state()

    def add_thought_status_msg(self, msg: str):
        self.thought_status_msgs.append(msg)
        self.save_to_session_state()

    def get_thought_status(self) -> Literal["running", "complete", "error"]:
        if self.thought_had_error:
            return "error"
        elif self.thought_complete:
            return "complete"
        return "running"


def trigger_chain_of_thought(session: ThoughtData, model: str):
    session.trigger_new_thought = True
    session.thought_model = model


def _dump(obj: BaseModel | BaseSettings) -> str:
    obj.model_dump_json()
    return json.dumps(json.loads(obj.model_dump_json()), indent=2, sort_keys=True)


def main():
    settings = StreamlitAppSettings.load()
    session_data = ThoughtData.init_session(settings.session_data)
    main_tab, knowledge_tab, thoughts_tab, debug_tab = st.tabs(["Main", "Knowledgebase", "Recent Thoughts", "Debug"])

    try:
        with knowledge_tab:
            render_knowledgebase(settings)

        with thoughts_tab:
            render_recent_thoughts(settings)

        with main_tab:
            render_main_functionality(settings, session_data)
    finally:
        with debug_tab:
            with st.expander("Settings"):
                st.code(_dump(settings))
            with st.expander("Session", expanded=True):
                st.button("Clear session data", on_click=_clear_thought, args=[session_data])
                st.code(_dump(session_data))


def render_main_functionality(settings: StreamlitAppSettings, session_data: ThoughtData):
    chat_col, sidebar = st.columns((2, 2))

    if not session_data.trigger_new_thought:
        with chat_col:
            with st.chat_message(name="ai", avatar="assistant"):
                st.write("Awaiting thought...")
        with sidebar:
            with st.form("New thought"):
                model = st.selectbox("Thought model", ("gpt-3.5-turbo", "gpt-4"))
                if st.form_submit_button("Trigger new thought"):
                    trigger_chain_of_thought(session_data, model)
                    st.experimental_rerun()

            st.write("OR")
            thought_id = st.text_input("Load specific thought")
            st.write("OR")
            if not thought_id:
                sessions = sorted(
                    [x.name.removesuffix(".json") for x in settings.session_data.iterdir()],
                    reverse=True,
                )

                thought_id = st.selectbox("Select specific thought", [""] + sessions)

            if thought_id:
                session_data.clear_session()
                st.experimental_set_query_params(s=thought_id)
                st.experimental_rerun()

        st.stop()

    # brain = Brain(settings=settings, model="gpt-4")
    brain = Brain(logger=logger, settings=settings, model=session_data.thought_model)
    with sidebar:
        status = st.status("This thought chain", state=session_data.get_thought_status(), expanded=True)
        continue_button = st.empty()
        st.divider()
        st.button("Clear thought", on_click=_clear_thought, args=[session_data], type="primary")
        st.caption("This does not stop the thought from processing")
    status_msgs = status.container().empty()

    def _display_status_msgs():
        status_msgs.code("\n".join(session_data.thought_status_msgs))

    def _add_status_msg(msg: str):
        session_data.add_thought_status_msg(msg)
        _display_status_msgs()

    if not session_data.thought_status_msgs:
        _add_status_msg(f"Thought initiated {session_data.session_id}")
        _add_status_msg(f"Thought Model: {session_data.thought_model}")

    _display_status_msgs()

    with chat_col:
        with st.chat_message(name="ai", avatar="assistant"):
            with st.expander("Current Brain Context"):
                brain_context = st.empty()
        with st.chat_message(name="user"):
            with st.expander("Prompt for new thought chain"):
                st.write(prompts.START_NEW_THOUGHT_PROMPT)
        with st.chat_message(name="ai", avatar="assistant"):
            if not session_data.new_thought:
                with st.spinner("Selecting thought type..."):
                    session_data.new_thought = brain.get_new_thought_type()
                    _add_status_msg(f"Thought Type: {session_data.new_thought.response_type}")
                    session_data.persist_session_state(settings.session_data)

            label = f"Chosen thought type: {session_data.new_thought.response_type}"
            with st.expander(label):
                st.write(str(session_data.new_thought))

        if continue_button.button("Continue thought chain"):
            with st.spinner("Continuing thought chain..."):
                thought_response = brain.run_reflect_thought(
                    session_data.new_thought.rationale, previous_thought_responses=session_data.this_thought_responses
                )
            session_data.add_reflect_thought_response(thought_response)
            _add_status_msg(f"Action: {thought_response.response_type}")
            session_data.persist_session_state(settings.session_data)

        # display responses in the thought chain
        if session_data.this_thought_responses:
            if session_data.new_thought.response_type == ThoughtTypes.REFLECT:
                thought_prompt_label = "REFLECT thought prompt"
                thought_prompt = prompts.REFLECT_PROMPT.format(rationale=session_data.new_thought.rationale)
                thought_responses = session_data.this_thought_responses

                with st.chat_message(name="user"):
                    with st.expander(thought_prompt_label):
                        st.write(thought_prompt)

                for idx, thought_response in enumerate(thought_responses):
                    response_label = thought_response.response_type
                    with st.chat_message(name="ai", avatar="assistant"):
                        with st.expander(response_label):
                            st.write(str(thought_response))
                    # last one?
                    if idx + 1 == len(thought_responses):
                        continue
            else:
                raise ValueError(f"Unsupported thought_type: {session_data.new_thought.response_type}")

    brain_context.write(brain.standard_chat_context())
    status.update(state="complete")
    _display_status_msgs()


def grey_color_func(word, font_size, position, orientation, random_state=None, **kwargs):
    return "hsl(0, 0%%, %d%%)" % random.randint(60, 100)


def _clear_thought(session: ThoughtData):
    session.clear_session()
    st.experimental_set_query_params(s="")


def render_recent_thoughts(settings: StreamlitAppSettings, n=5):
    Brain(logger=logger, settings=settings)
    here = Path(__file__).parent

    brain_mask = np.array(Image.open(str(here / "brain-outline.png")))
    settings.session_data.mkdir(exist_ok=True, parents=True)
    text = []
    for session_file in sorted([x.name for x in settings.session_data.iterdir()], reverse=True)[:n]:
        session_text = (settings.session_data / session_file).read_text()
        obj = ThoughtData.model_validate_json(session_text)
        text.append(obj.new_thought.rationale)

    stopwords = set(STOPWORDS)

    if text:
        wc = WordCloud(
            max_words=2000,
            scale=2,
            background_color="white",
            stopwords=stopwords,
            contour_width=1,
            contour_color="black",
            # color_func=grey_color_func,
            mask=brain_mask,
        )

        # generate word cloud
        wc.generate("\n".join(text))
        wordcloud = wc.to_array()
        st.image(wordcloud)
    else:
        st.write("No recent thoughts")


def render_knowledgebase(settings: StreamlitAppSettings):
    pass


if __name__ == "__main__":
    main()
