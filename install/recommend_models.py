import subprocess

def get_vram():

    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            text=True
        )

        return int(out.strip())

    except:
        return None


def recommend(vram):

    if vram is None:
        print("CPU mode recommended")
        return

    print("Detected VRAM:", vram, "MB")

    if vram < 8000:
        print("Recommended model: 7B Q4_K_M")

    elif vram < 16000:
        print("Recommended model: 13B Q4_K_M")

    else:
        print("Recommended model: 20B Q4_K_M")


if __name__ == "__main__":

    recommend(get_vram())