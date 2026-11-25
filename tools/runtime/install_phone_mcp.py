"""Register APK-owned Android & Phone MCP servers and skills into Google Antigravity (~/.gemini/config/)."""
import json
import os
from pathlib import Path, PurePosixPath

SHARE = PurePosixPath('/usr/local/share/codex')
PLUGIN = PurePosixPath('plugins/agy-android')
DEVICE_SCRIPT = SHARE / PLUGIN / 'scripts/server.py'
RELAY_SCRIPT = SHARE / PLUGIN / 'scripts/phone_relay.py'
PHONE_SKILL = SHARE / PLUGIN / 'skills/phone/SKILL.md'
ANDROID_SKILL = SHARE / PLUGIN / 'skills/android/SKILL.md'


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == rendered:
        return
    temp = path.with_suffix(path.suffix + '.next')
    temp.write_text(rendered, encoding='utf-8')
    temp.replace(path)


def _sync_skill(src: Path, dst: Path) -> None:
    if not src.is_file():
        return
    contents = src.read_bytes()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists() or dst.read_bytes() != contents:
        temp = dst.with_suffix('.next')
        temp.write_bytes(contents)
        temp.replace(dst)


def prepare(env=None):
    env = dict(os.environ if env is None else env)
    gemini_home = Path(env.get('AGY_HOME') or str(Path(env['HOME']) / '.gemini'))
    config_dir = gemini_home / 'config'
    config_dir.mkdir(parents=True, exist_ok=True)

    tools_dir = env.get('CODEX_TOOLS_DIR', '')
    phone_bridge = str(Path(tools_dir) / 'phone-bridge.json') if tools_dir else str(SHARE / 'phone/bridge.json')
    android_bridge = str(SHARE / 'android-bridge.json')

    clean_env = {
        'LD_LIBRARY_PATH': '',
        'LD_PRELOAD': '',
        'PYTHONDONTWRITEBYTECODE': '1',
    }
    phone_server = {
        'command': '/usr/bin/python3',
        'args': ['-I', '-B', str(RELAY_SCRIPT), phone_bridge],
        'env': clean_env,
    }
    android_server = {
        'command': '/usr/bin/python3',
        'args': ['-I', '-B', str(DEVICE_SCRIPT), android_bridge],
        'env': clean_env,
    }

    mcp_path = config_dir / 'mcp_config.json'
    if mcp_path.is_file():
        try:
            config = json.loads(mcp_path.read_text(encoding='utf-8'))
            if not isinstance(config, dict):
                config = {}
        except ValueError:
            config = {}
    else:
        config = {}

    servers = config.get('mcpServers')
    if not isinstance(servers, dict):
        servers = {}
        config['mcpServers'] = servers

    servers['phone'] = phone_server
    servers['agy_android'] = android_server
    _atomic_write_json(mcp_path, config)

    # Install Antigravity global skills under ~/.gemini/config/skills/
    _sync_skill(Path(str(PHONE_SKILL)), config_dir / 'skills/agy-phone/SKILL.md')
    _sync_skill(Path(str(ANDROID_SKILL)), config_dir / 'skills/agy-android/SKILL.md')

    return {
        'mcpConfig': str(mcp_path),
        'phoneMcp': 'registered',
        'androidMcp': 'registered',
        'skills': ['agy-phone', 'agy-android'],
    }


if __name__ == '__main__':
    print(json.dumps(prepare()))
