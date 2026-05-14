import subprocess
import yaml
from pathlib import Path

CONFIG = Path("config.yaml")


def get_vram():

    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            text=True
        )

        return int(out.strip())

    except:
        return None


def recommend_context(vram):

    if vram is None:
        return 1024

    if vram < 8000:
        return 2048

    if vram < 16000:
        return 4096

    return 4096


def write_config():

    vram = get_vram()

    context = recommend_context(vram)

    config = {

        "model": "models/mistral-7b-instruct-v0.3.Q4_K_M.gguf",

        "llama":

            {
                "context_length": context,
                "gpu_layers": -1
            }

    }

    with open(CONFIG, "w") as f:
        yaml.dump(config, f)

    print("config.yaml generated")
    print("context_length:", context)


if __name__ == "__main__":
    write_config()