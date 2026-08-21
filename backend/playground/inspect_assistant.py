"""Run each # %% cell with Shift+Enter in the backend IPython kernel."""

# ruff: noqa: F704, PLE1142, B018 - IPython supports top-level await and display.

# %% Imports
from getpass import getpass

import nest_asyncio2

from evaluation.inspect_assistant import inspect_assistant

nest_asyncio2.apply()


# %% Paste the authenticated Supabase token when the prompt appears
ACCESS_TOKEN = getpass("Supabase access token: ")


# %% Edit the question
QUESTION = "What apple product had the most sales in 2024?"

# Other question ideas:
# "What risks did NVIDIA identify around manufacturing capacity?"
# "How fast did Azure and other cloud services grow and what drove it?"


# %% Run the complete grounded-assistant workflow
inspection = await inspect_assistant(QUESTION, ACCESS_TOKEN)


# %% Inspect the validated answer
inspection.result.answer


# %% Inspect every current-turn source and whether it was read/cited
inspection.evidence
