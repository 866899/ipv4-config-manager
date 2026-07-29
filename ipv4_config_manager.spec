# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 - IPv4 配置管理器。

打包命令:
    pyinstaller ipv4_config_manager.spec

产物: dist/IPv4ConfigManager.exe (单文件, 无控制台)
"""

block_cipher = None

a = Analysis(
    ['ip_config_manager.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大模块, 减小体积
        'unittest',
        'pydoc',
        'doctest',
        'argparse',
        'xml',
        'email',
        'html',
        'http',
        'urllib',
        'ftplib',
        'imaplib',
        'nntplib',
        'smtplib',
        'telnetlib',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='IPv4ConfigManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # 无控制台窗口 (GUI 程序)
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',  # 如有图标可取消注释
)
