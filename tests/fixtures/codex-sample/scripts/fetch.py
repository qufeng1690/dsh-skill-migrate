import os


def home():
    return os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))


if __name__ == "__main__":
    print(home())
