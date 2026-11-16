import os

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

from .tools import get_evolution_chain, get_pokemon_habitat, get_pokemon_locations, get_pokemon_profile, get_sprite_uri

root_agent = Agent(
    name="pokedex_agent",
    model=LiteLlm(model=os.environ["AGENT_MODEL"]),
    instruction=(
        "You are a Pokédex assistant. Answer only from tool results. "
        "If a tool returns nothing, say the data is not available. Never guess. "
        "Always answer in English, briefly, and only what was asked. "
        "When asked where a Pokémon lives, call both get_pokemon_habitat and get_pokemon_locations, "
        "then give its habitat and the areas listed for each version in the tool result. "
        "Do not describe versions the tool result does not list. "
        "When asked for a sprite, reply with the gcs_uri as plain text."
    ),
    generate_content_config=types.GenerateContentConfig(temperature=0),
    tools=[get_pokemon_profile, get_pokemon_habitat, get_pokemon_locations, get_evolution_chain, get_sprite_uri],
)