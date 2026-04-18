#!/usr/bin/env python3
"""
音乐播放器核心模块
支持格式：MP3, WAV, AVI, MP4, MKV 等常见音视频格式
"""

import pygame
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
import re


@dataclass
class Track:
    """播放列表项"""
    path: str
    title: str


class AudioPlayer:
    """音频播放器（MP3, WAV 等）"""

    def __init__(self):
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        self.is_playing = False
        self.is_paused = False
        self.current_track: Optional[Track] = None
        self.queue: List[Track] = []

    def play_file(self, filepath: str) -> bool:
        """播放单个文件"""
        try:
            pygame.mixer.music.load(filepath)
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            pygame.mixer.music.play()
            self.current_track = Track(path=filepath, title=Path(filepath).name)
            self.is_playing = True
            self.is_paused = False
            return True
        except Exception as e:
            print(f"播放失败：{e}")
            return False

    def play_queue(self, files: List[str]) -> bool:
        """从队列播放"""
        try:
            if not files:
                return False
            pygame.mixer.music.queue(files[-1])  # 先加载最后一个
            pygame.mixer.music.load(files[0])
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            pygame.mixer.music.play()
            self.queue = [Track(path=f, title=Path(f).name) for f in files]
            self.current_track = self.queue[0]
            self.is_playing = True
            self.is_paused = False
            return True
        except Exception as e:
            print(f"播放队列失败：{e}")
            return False

    def pause(self):
        """暂停播放"""
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.pause()
            self.is_paused = True

    def resume(self):
        """恢复播放"""
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.unpause()
            self.is_paused = False

    def stop(self):
        """停止播放"""
        pygame.mixer.music.stop()
        self.is_playing = False
        self.is_paused = False
        self.current_track = None

    def is_active(self) -> bool:
        """是否正在播放"""
        return pygame.mixer.music.get_busy() > 0 or (self.is_playing and not pygame.mixer.music.get_busy())


class VideoPlayer:
    """视频播放器（AVI, MP4, MKV 等）"""

    def __init__(self):
        self.is_playing = False
        self.current_file: Optional[str] = None
        import cv2
        self.cap = None
        self.frame_delay = 0.033  # 约 30fps

    def play_video(self, filepath: str) -> bool:
        """播放视频文件"""
        try:
            if not self._close():
                print("关闭失败，强制重新打开")
            self.cap = cv2.VideoCapture(filepath)
            if not self.cap.isOpened():
                return False
            # 设置输出窗口大小
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cv2.namedWindow('PyPlayer Video', cv2.WINDOW_NORMAL)
            cv2.resizeWindow('PyPlayer Video', min(width, 1280), min(height, 720))
            self.current_file = filepath
            self.is_playing = True
            return True
        except Exception as e:
            print(f"视频播放失败：{e}")
            import traceback
            traceback.print_exc()
            return False

    def _close(self):
        """关闭当前视频"""
        if self.cap is not None and self.cap.isOpened():
            try:
                self.cap.release()
            except:
                pass
            self.cap = None
        try:
            cv2.destroyWindow('PyPlayer Video')
        except:
            pass

    def render_frame(self) -> bool:
        """渲染一帧"""
        if not self.is_playing or self.cap is None:
            return False
        ret, frame = self.cap.read()
        if not ret:
            self.stop()  # 视频播完
            return False
        cv2.imshow('PyPlayer Video', frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            self.stop()
            print("用户退出视频播放")
            return False
        import time
        time.sleep(self.frame_delay)
        return True

    def stop(self):
        """停止播放"""
        self._close()
        self.is_playing = False


class PlayerManager:
    """播放器管理器，自动选择音频或视频模式"""

    SUPPORTED_AUDIO = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac'}
    SUPPORTED_VIDEO = {'.avi', '.mp4', '.mkv', '.mov', '.wmv'}

    def __init__(self):
        self.audio_player = AudioPlayer()
        self.video_player = None
        self._is_video_playing = False

    def get_supported_formats(self) -> dict:
        """获取支持的格式"""
        return {
            "音频": list(sorted(self.SUPPORTED_AUDIO)),
            "视频": list(sorted(self.SUPPORTED_VIDEO))
        }

    def _check_file_type(self, filepath: str) -> Optional[str]:
        """判断文件类型：audio 或 video"""
        ext = Path(filepath).suffix.lower()
        if ext in self.SUPPORTED_AUDIO:
            return 'audio'
        elif ext in self.SUPPORTED_VIDEO:
            return 'video'
        else:
            return None

    def play(self, filepath: str) -> bool:
        """播放文件（自动选择模式）"""
        # 先停止之前可能正在播放的
        if self._is_video_playing and self.video_player:
            self.video_player.stop()

        file_type = self._check_file_type(filepath)
        if not file_type:
            print(f"不支持的文件格式：{filepath}")
            return False

        try:
            import pygame.mixer
            pygame.mixer.quit()
            import cv2
            cv2.destroyAllWindows()
        except:
            pass

        # 重新初始化
        self.audio_player = AudioPlayer()
        self.video_player = VideoPlayer()
        self._is_video_playing = False

        if file_type == 'audio':
            result = self.audio_player.play_file(filepath)
        else:
            import cv2
            self._is_video_playing = True
            result = self.video_player.play_video(filepath)

        return result

    def play_playlist(self, files: List[str]) -> bool:
        """播放列表"""
        if not files:
            return False

        audio_files = [f for f in files if self._check_file_type(f) == 'audio']
        video_files = [f for f in files if self._check_file_type(f) == 'video']

        # 先处理音频列表
        if audio_files:
            import pygame.mixer
            pygame.mixer.quit()
            self.audio_player = AudioPlayer()
            result = self.audio_player.play_queue(audio_files)
            if result and len(video_files) > 0:
                print(f"\n开始播放视频：{video_files[0]}")
                self._is_video_playing = True

        # 处理视频列表
        for video in video_files:
            import cv2
            self.video_player = VideoPlayer()
            if not self.video_player.play_video(video):
                return False

        return len(audio_files) > 0 or len(video_files) > 0

    def get_status(self) -> dict:
        """获取当前播放状态"""
        import pygame.mixer
        try:
            pygame.mixer.init()
        except:
            pass
        return {
            "audio_playing": self.audio_player.is_active(),
            "video_playing": self._is_video_playing,
            "current_track": self.audio_player.current_track.title if self.audio_player.current_track else None,
            "paused": self.audio_player.is_paused
        }

    def get_playlist(self) -> list:
        """获取当前播放列表（仅音频）"""
        return self.audio_player.queue if hasattr(self.audio_player, 'queue') else []

    def pause(self):
        """暂停播放"""
        import pygame.mixer
        try:
            pygame.mixer.init()
        except:
            pass
        if not self._is_video_playing:
            self.audio_player.pause()
        else:
            import cv2
            # 视频暂停会显示当前帧，不实际暂停解码

    def resume(self):
        """恢复播放"""
        import pygame.mixer
        try:
            pygame.mixer.init()
        except:
            pass
        if not self._is_video_playing:
            self.audio_player.resume()
        else:
            # 视频继续渲染帧
            if self.video_player and self.video_player.render_frame():
                import time
                while True:
                    import cv2
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('r'):  # r 恢复
                        break
                    elif key == ord('q'):
                        return

    def stop(self):
        """停止播放"""
        import pygame.mixer
        try:
            pygame.mixer.init()
        except:
            pass
        self.audio_player.stop()
        if self._is_video_playing and self.video_player:
            self.video_player.stop()
        self._is_video_playing = False

    def toggle_play_pause(self):
        """切换播放/暂停状态"""
        import pygame.mixer
        try:
            pygame.mixer.init()
        except:
            pass

        if self._is_video_playing and self.video_player:
            # 视频：不能简单暂停，显示当前帧
            return False

        status = self.audio_player.get_status()
        if not status['current_track']:
            return False

        if status['paused']:
            self.resume()
            return True
        else:
            self.pause()
            return True

    def next_track(self):
        """切换到下一首"""
        # 简单实现：重新播放当前文件（实际项目中可以使用队列）
        pass


def create_manager():
    """创建播放器管理器单例"""
    import pygame
    import cv2
    # 先初始化 pygame mixer，避免后续问题
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    except Exception as e:
        print(f"音频模块初始化警告：{e}")

    # 设置 OpenCV 显示后端（避免与 Pygame 冲突）
    try:
        cv2.namedWindow('PyPlayer Video', cv2.WINDOW_NORMAL)
        cv2.destroyWindow('PyPlayer Video')
    except Exception as e:
        print(f"视频模块初始化警告：{e}")

    return PlayerManager()


def main():
    """简单测试"""
    print("=== PyPlayer 播放器测试 ===")
    player = create_manager()

    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        result = player.play(filepath)
        if not result:
            return 1

        # 持续播放直到完成或用户退出
        while True:
            status = player.get_status()
            import time

            if status['audio_playing']:
                time.sleep(0.1)
            elif status['video_playing'] and player.video_player:
                import cv2
                key = cv2.waitKey(33) & 0xFF
                if key == ord('q'):
                    break
            else:
                break

        print("播放完成或已停止")
        return 0
    else:
        # 显示支持的格式
        formats = player.get_supported_formats()
        print(f"\n支持音频格式：{', '.join(formats['音频'])}")
        print(f"支持视频格式：{', '.join(formats['视频'])}\n")


def launch_tui():
    """启动终端 UI 模式"""
    try:
        from tui import main as tui_main
        import curses
        curses.wrapper(tui_main)
    except ImportError:
        print("TUI module not found. Please ensure tui.py exists.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ('-t', '--tui'):
        launch_tui()
    else:
        main()
