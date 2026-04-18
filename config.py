#!/usr/bin/env python3
"""
PyPlayer 配置管理模块
负责 settings.xml 的读写操作，提供媒体库配置的持久化存储
"""

import os
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional
import xml.etree.ElementTree as ET
from datetime import datetime


@dataclass
class LibraryConfig:
    """表示单个媒体库配置"""
    path: str
    name: Optional[str] = None

    def __post_init__(self):
        if self.name is None:
            self.name = Path(self.path).name


@dataclass
class Settings:
    """表示完整系统配置"""
    media_libraries: List[LibraryConfig] = field(default_factory=list)

    def add_library(self, path: str, name: Optional[str] = None) -> LibraryConfig:
        """添加媒体库并返回配置对象"""
        lib_config = LibraryConfig(path=path, name=name)
        if not self.get_library_by_path(path):
            self.media_libraries.append(lib_config)
        return lib_config

    def remove_library(self, path: str) -> bool:
        """删除指定路径的媒体库，返回是否成功"""
        path = os.path.normpath(path)
        for i, lib in enumerate(self.media_libraries):
            if os.path.normpath(lib.path) == path:
                del self.media_libraries[i]
                return True
        return False

    def get_library_by_path(self, path: str) -> Optional[LibraryConfig]:
        """根据路径查找媒体库配置"""
        path = os.path.normpath(path)
        for lib in self.media_libraries:
            if os.path.normpath(lib.path) == path:
                return lib
        return None


class SettingsManager:
    """配置文件读写管理器"""

    DEFAULT_FILE = "settings.xml"

    def __init__(self, config_file: Optional[str] = None):
        self.config_file = Path(config_file or self.DEFAULT_FILE).resolve()
        self._settings: Optional[Settings] = None
        # 自动加载配置
        _ = self.settings

    @property
    def settings(self) -> Settings:
        """获取当前配置（如果尚未加载则自动读取）"""
        if self._settings is None:
            self.load()
        return self._settings

    def load(self) -> Settings:
        """从文件加载配置，失败时返回空配置"""
        try:
            # 首次运行：创建配置文件
            if not self.config_file.exists():
                self._create_empty_config()
                self.save()
                return self._settings

            tree = ET.parse(self.config_file)
            root = tree.getroot()

            libraries = []
            media_libs_elem = root.find("media_libraries")
            if media_libs_elem is not None:
                for lib_elem in media_libs_elem.findall("library"):
                    path = lib_elem.get("path", "")
                    name = lib_elem.get("name", None)
                    if path:
                        libraries.append(LibraryConfig(path=path, name=name))

            self._settings = Settings(media_libraries=libraries)
            return self._settings

        except ET.ParseError as e:
            print(f"警告：配置文件损坏，使用空配置：{e}")
            self._settings = Settings()
            return self._settings
        except Exception as e:
            print(f"警告：加载配置失败：{e}，使用空配置")
            self._settings = Settings()
            return self._settings

    def save(self) -> bool:
        """保存当前配置到文件"""
        try:
            # 确保父目录存在
            parent_dir = self.config_file.parent
            if not parent_dir.exists():
                parent_dir.mkdir(parents=True, exist_ok=True)

            root = ET.Element("settings")
            root.set("last_updated", datetime.now().isoformat())

            media_libs = ET.SubElement(root, "media_libraries")
            for lib in self._settings.media_libraries:
                lib_elem = ET.SubElement(media_libs, "library")
                lib_elem.set("path", os.path.normpath(lib.path))
                if lib.name and lib.name != Path(lib.path).name:
                    lib_elem.set("name", lib.name)

            # 格式化 XML 输出
            tree_str = ET.tostring(root, encoding="unicode")
            from xml.dom import minidom
            parsed = minidom.parseString(tree_str)
            pretty_xml = parsed.toprettyxml(indent="    ")
            # 移除多出来的空行
            lines = [line for line in pretty_xml.splitlines() if line.strip()]
            pretty_xml = "\n".join(lines)

            with open(self.config_file, "w", encoding="utf-8") as f:
                f.write(pretty_xml)

            return True

        except Exception as e:
            print(f"保存配置失败：{e}")
            return False

    def add_library(self, path: str, name: Optional[str] = None) -> bool:
        """添加媒体库并立即保存到文件"""
        if not os.path.exists(path):
            print(f"路径不存在：{path}")
            return False

        self.settings.add_library(path=path, name=name)
        return self.save()

    def remove_library(self, path: str) -> bool:
        """删除媒体库并立即保存到文件"""
        if not self.settings.remove_library(path):
            print(f"未找到该媒体库：{path}")
            return False

        return self.save()

    def _create_empty_config(self):
        """创建空的配置文件"""
        root = ET.Element("settings")
        root.set("last_updated", datetime.now().isoformat())
        ET.SubElement(root, "media_libraries")

        tree_str = ET.tostring(root, encoding="unicode")
        from xml.dom import minidom
        parsed = minidom.parseString(tree_str)
        pretty_xml = parsed.toprettyxml(indent="    ")
        lines = [line for line in pretty_xml.splitlines() if line.strip()]

        with open(self.config_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
