
from huggingface_hub import hf_hub_download
from pathlib import Path
 
MODELS = [
    {
        "repo": "TheBloke/Mistral-7B-Instruct-v0.3-GGUF",
        "file": "mistral-7b-instruct-v0.3.Q4_K_M.gguf"
    },
    {
        "repo": "bartowski/gpt-oss-20b-GGUF",
        "file": "gpt-oss-20b.Q4_K_M.gguf"
    }
]
 
MODEL_DIR = Path("models")
MODEL_DIR.mkdir(exist_ok=True)
 
 
def download(repo, file):
    print("Downloading:", file)
    hf_hub_download(
        repo_id=repo,
        filename=file,
        local_dir=MODEL_DIR,
    )
 
 
def main():
    for m in MODELS:
        path = MODEL_DIR / m["file"]
        if path.exists():
            print("Model already present:", m["file"])
            continue
        download(m["repo"], m["file"])
 
 
if __name__ == "__main__":
    main()
