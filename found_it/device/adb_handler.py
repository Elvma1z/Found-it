import subprocess
import shutil
import os
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class DeviceInfo:
    serial: str
    model: str
    status: str


@dataclass
class DeviceFile:
    path: str
    name: str
    size_bytes: int
    is_dir: bool
    extension: str = ""
    modified_time: float = 0


class ADBHandler:
    def __init__(self):
        self.adb_path = self._find_adb()
        self.connected_device: Optional[DeviceInfo] = None

    def _find_adb(self) -> Optional[str]:
        path = shutil.which("adb")
        if path:
            return path

        common_paths = [
            os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
            r"C:\platform-tools\adb.exe",
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Android\Sdk\platform-tools\adb.exe"),
            "/usr/bin/adb",
            "/usr/local/bin/adb",
            "/opt/android-sdk/platform-tools/adb",
        ]
        for p in common_paths:
            if os.path.isfile(p):
                return p

        return None

    def is_available(self) -> bool:
        return self.adb_path is not None

    def _run(self, args: list, timeout: int = 10) -> Tuple[bool, str]:
        if not self.adb_path:
            return False, "ADB not found"

        cmd = [self.adb_path] + args
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW
                if os.name == "nt" else 0
            )
            return result.returncode == 0, result.stdout.strip()
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def _run_device(self, args: list, timeout: int = 30) -> Tuple[bool, str]:
        if not self.connected_device:
            return False, "No device connected"
        return self._run(["-s", self.connected_device.serial] + args, timeout)

    def get_devices(self) -> List[DeviceInfo]:
        ok, output = self._run(["devices", "-l"])
        if not ok:
            return []

        devices = []
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serial = parts[0]
                model = "Unknown"
                for part in parts[2:]:
                    if part.startswith("model:"):
                        model = part.split(":", 1)[1]
                devices.append(DeviceInfo(serial=serial, model=model, status="device"))

        return devices

    def connect_device(self, serial: Optional[str] = None) -> bool:
        devices = self.get_devices()
        if not devices:
            return False
        if serial:
            match = next((d for d in devices if d.serial == serial), None)
            if not match:
                return False
            self.connected_device = match
            return True
        self.connected_device = devices[0]
        return True

    def disconnect(self):
        self.connected_device = None

    def get_device_model(self) -> str:
        if not self.connected_device:
            return "Unknown"
        ok, model = self._run_device(["shell", "getprop", "ro.product.model"])
        return model if ok else self.connected_device.model

    def list_files(self, remote_path: str) -> List[DeviceFile]:
        ok, output = self._run_device(
            ["shell", f"find '{remote_path}' -maxdepth 1 -type f -o -type d | head -500"],
            timeout=15
        )
        if not ok:
            return []

        files = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line == remote_path:
                continue

            name = os.path.basename(line)
            ext = os.path.splitext(name)[1].lower()
            is_dir = not "." in name or line.endswith("/")

            files.append(DeviceFile(
                path=line,
                name=name,
                size_bytes=0,
                is_dir=is_dir,
                extension=ext,
            ))

        return files

    def scan_storage(self, paths: Optional[List[str]] = None,
                     progress_callback=None) -> List[DeviceFile]:
        if not self.connected_device:
            return []

        if paths is None:
            paths = ["/sdcard/", "/storage/emulated/0/"]

        all_files = []
        scan_dirs = list(paths)

        scanned = 0
        while scan_dirs:
            current = scan_dirs.pop(0)

            ok, output = self._run_device(
                ["shell", f"ls -la '{current}'"],
                timeout=10
            )
            if not ok:
                continue

            for line in output.splitlines():
                parts = line.split(None, 7)
                if len(parts) < 8:
                    continue

                perms = parts[0]
                name = parts[-1]

                if name in (".", ".."):
                    continue

                full_path = f"{current.rstrip('/')}/{name}"
                is_dir = perms.startswith("d")

                try:
                    size = int(parts[4]) if not is_dir else 0
                except (ValueError, IndexError):
                    size = 0

                ext = os.path.splitext(name)[1].lower() if not is_dir else ""

                if is_dir:
                    scan_dirs.append(full_path + "/")
                    continue

                scanned += 1
                if scanned % 50 == 0 and progress_callback:
                    progress_callback(f"Scanning: {scanned} files... {name}")

                all_files.append(DeviceFile(
                    path=full_path,
                    name=name,
                    size_bytes=size,
                    is_dir=False,
                    extension=ext,
                ))

        return all_files

    def pull_file(self, remote_path: str, local_dir: str) -> Optional[str]:
        local_path = os.path.join(local_dir, os.path.basename(remote_path))
        ok, _ = self._run_device(
            ["pull", remote_path, local_path],
            timeout=60
        )
        return local_path if ok and os.path.exists(local_path) else None

    def read_file_text(self, remote_path: str, max_bytes: int = 50000) -> str:
        ok, output = self._run_device(
            ["shell", f"head -c {max_bytes} '{remote_path}'"],
            timeout=10
        )
        return output if ok else ""

    def get_storage_paths(self) -> List[str]:
        paths = []
        ok, output = self._run_device(
            ["shell", "ls /storage/"],
            timeout=5
        )
        if ok:
            for entry in output.splitlines():
                entry = entry.strip()
                if entry and entry not in (".", "..", "self", "emulated", "sdcard0"):
                    paths.append(f"/storage/{entry}/")
                elif entry == "emulated":
                    paths.append("/storage/emulated/0/")

        if not paths:
            paths = ["/sdcard/", "/storage/emulated/0/"]

        return paths
