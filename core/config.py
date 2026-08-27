import json
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config():
    """加载项目根目录下的 config.json"""
    config_path = os.path.join(_PROJECT_ROOT, "config.json")
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)
