#
# Copyright 2023 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Rate limited Gemini wrapper"""

import os

import google.generativeai
from ratelimit import limits, sleep_and_retry
from typing import List
from docs_agent.utilities.config import Models


class Error(Exception):
    """Base error class for Gemini"""


class GoogleNoAPIKeyError(Error, RuntimeError):
    """Raised if no API key is provided nor found in environment variable."""

    def __init__(self) -> None:
        super().__init__(
            "Google API key is not provided "
            "or set in the environment variable GOOGLE_API_KEY"
        )


class GoogleUnsupportedModelError(Error, RuntimeError):
    """Raised if a specified model is not supported by the endpoint."""

    def __init__(self, model, api_endpoint) -> None:
        super().__init__(
            f"The specified model {model} is not supported "
            f"on the API endpoint {api_endpoint}"
        )


class Gemini:
    """Rate limited Gemini wrapper

    This class exposes Gemini's chat, text, and embedding API, but with a rate limit.
    Besides the rate limit, the `chat` and `generate_text` method has the same name and
    behavior as `google.generativeai.chat` and `google.generativeai.generate_text`,
    respectively. The `embed` method is different from
    `google.generativeai.generate_embeddings` since `embed` returns List[float]
    while `google.generativeai.generate_embeddings` returns a dict. And that's why it
    has a different name.
    """

    minute = 60  # seconds in a minute
    max_embed_per_minute = 1400
    max_text_per_minute = 30

    # MAX_MESSAGE_PER_MINUTE = 30
    def __init__(self, models_config: Models) -> None:
        self.api_endpoint = models_config.api_endpoint
        self.api_key = models_config.api_key
        self.embed_model = models_config.embedding_model
        self.language_model = models_config.language_model
        self.embedding_api_call_limit = models_config.embedding_api_call_limit
        self.embedding_api_call_period = models_config.embedding_api_call_period

        # Configure the model
        google.generativeai.configure(
            api_key=self.api_key, client_options={"api_endpoint": self.api_endpoint}
        )
        # Check whether the specified models are supported
        supported_models = set(
            model.name for model in google.generativeai.list_models()
        )
        for model in (models_config.language_model, models_config.embedding_model):
            if model not in supported_models:
                raise GoogleUnsupportedModelError(model, self.api_endpoint)

    # TODO bring in limit values from config files
    @sleep_and_retry
    @limits(calls=max_embed_per_minute, period=minute)
    def embed(
        self, content, task_type: str = "RETRIEVAL_QUERY", title: str = None
    ) -> List[float]:
        if self.embed_model == "models/embedding-001":
            return [
                google.generativeai.embed_content(
                    model=self.embed_model,
                    content=content,
                    task_type=task_type,
                    title=title,
                )["embedding"]
            ]
        else:
            raise GoogleNoModelError(func_name="embed", attr="embed_model")

    # TODO bring in limit values from config files
    @sleep_and_retry
    @limits(calls=max_text_per_minute, period=minute)
    def generate_content(self, contents):
        if self.language_model is None:
            raise GoogleNoModelError(func_name="generate_content", attr="content_model")
        model = google.generativeai.GenerativeModel(model_name=self.language_model)
        return model.generate_content(contents)

    # Use this method for talking to a Gemini content model
    # Optionally provide a prompt, if not use the one from config.yaml
    # If prompt is "fact_checker" it will use the fact_check_question from
    # config.yaml for the prompt
    def ask_content_model_with_context_prompt(
        self, context: str, question: str, prompt: str = None
    ):
        if prompt == None:
            prompt = self.prompt_condition
        elif prompt == "fact_checker":
            prompt = self.fact_check_question
        new_prompt = f"{prompt}\n\nQuestion: {question}\n\nContext:\n{context}"
        # Print the prompt for debugging if the log level is VERBOSE.
        if LOG_LEVEL == "VERBOSE":
            self.print_the_prompt(new_prompt)
        try:
            response = palm.generate_content(new_prompt)
        except google.api_core.exceptions.InvalidArgument:
            return self.model_error_message
        for chunk in response:
            if str(chunk.candidates[0].content) == "":
                return self.model_error_message
        return response.text, new_prompt

    # Use this method for asking a Gemini content model for fact-checking
    def ask_content_model_to_fact_check(self, context, prev_response):
        question = self.fact_check_question + "\n\nText: "
        question += prev_response
        return self.ask_content_model_with_context(context, question)
