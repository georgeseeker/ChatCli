"""开发时兼容：python main.py → 等同于 python -m chatcli。"""

from chatcli.main import main

if __name__ == "__main__":
    main()
