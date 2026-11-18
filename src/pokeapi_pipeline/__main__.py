from pokeapi_pipeline.pipeline.runner import PipelineRunner
from pokeapi_pipeline.util.config import Settings


if __name__ == "__main__":
    PipelineRunner(Settings()).run()
