"""Device Provider 인터페이스. 표준 ADB 구현이 기본이며, 통신 방식이 다른 장비는 이 인터페이스로 확장한다."""
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


@dataclass
class DeviceInfo:
    serial: str
    state: str = "device"  # device | unauthorized | offline
    manufacturer: str = ""
    model: str = ""
    android_version: str = ""
    sdk: int = 0
    cpu: str = ""
    ram_mb: int = 0
    storage_total_mb: int = 0
    storage_free_mb: int = 0
    battery: int = 0
    temperature: float = 0.0
    resolution: str = ""
    network: str = ""
    installed: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class ProviderError(Exception):
    """기기 제어 실패(ADB 오류, 연결 끊김 등)."""


class DeviceProvider(ABC):
    name = "base"

    @abstractmethod
    def list_serials(self) -> dict[str, str]:
        """{serial: state}"""

    @abstractmethod
    def describe(self, serial: str, packages: list[str]) -> DeviceInfo: ...

    @abstractmethod
    def install(self, serial: str, apk_path: str) -> tuple[bool, str]: ...

    def play_install(self, serial: str, package: str) -> tuple[bool, str]:
        """Play 스토어에서 설치(비공개 트랙 포함). 지원하지 않는 Provider는 기본값을 쓴다."""
        return False, "이 장비 연결 방식은 Play 스토어 설치를 지원하지 않습니다"

    @abstractmethod
    def uninstall(self, serial: str, package: str) -> tuple[bool, str]: ...

    @abstractmethod
    def installed_version(self, serial: str, package: str) -> str | None: ...

    @abstractmethod
    def launch(self, serial: str, package: str) -> dict:
        """{'ok': bool, 'total_ms': int|None, 'message': str}"""

    @abstractmethod
    def stop(self, serial: str, package: str) -> None: ...

    @abstractmethod
    def foreground_package(self, serial: str) -> str: ...

    @abstractmethod
    def pid_of(self, serial: str, package: str) -> int | None: ...

    @abstractmethod
    def screenshot(self, serial: str) -> bytes: ...

    @abstractmethod
    def dump_ui(self, serial: str) -> str: ...

    @abstractmethod
    def tap(self, serial: str, x: int, y: int) -> None: ...

    @abstractmethod
    def input_text(self, serial: str, text: str) -> None: ...

    @abstractmethod
    def swipe(self, serial: str, direction: str) -> None: ...

    @abstractmethod
    def key(self, serial: str, name: str) -> None:
        """name: HOME | BACK"""

    @abstractmethod
    def set_rotation(self, serial: str, landscape: bool | None) -> None:
        """True=가로, False=세로, None=자동 복원"""

    @abstractmethod
    def logcat_clear(self, serial: str) -> None: ...

    @abstractmethod
    def logcat_dump(self, serial: str) -> str: ...

    @abstractmethod
    def metrics(self, serial: str, package: str) -> dict:
        """{'cpu_percent','memory_mb','storage_mb','temperature_c'} 측정된 값만 포함"""

    @abstractmethod
    def permissions(self, serial: str, package: str) -> dict:
        """{'requested': [...], 'granted': [...]}"""

    @abstractmethod
    def set_network(self, serial: str, enabled: bool) -> bool:
        """네트워크 on/off. 수행할 수 없으면 False."""

    @abstractmethod
    def reboot(self, serial: str) -> None: ...

    @abstractmethod
    def reconnect(self, serial: str) -> str: ...

    @abstractmethod
    def push_file(self, serial: str, local_path: str, name: str) -> str: ...
