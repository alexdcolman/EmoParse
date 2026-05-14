import subprocess

def detect():

    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            text=True
        )

        name, vram = out.strip().split(",")

        vram = int(vram.strip().split()[0])

        print("GPU detected:", name.strip())
        print("VRAM:", vram, "MB")

        return vram

    except Exception:

        print("No NVIDIA GPU detected")
        return None


if __name__ == "__main__":
    detect()