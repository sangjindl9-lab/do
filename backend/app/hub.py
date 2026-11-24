"""에이전트 WebSocket 허브: 작업/명령이 생기면 해당 에이전트를 즉시 깨운다(실제 데이터는 HTTPS API로 주고받는다)."""
import asyncio
from collections import defaultdict


class Hub:
    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queues: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def register(self, agent_id: int) -> asyncio.Queue:
        self.loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self.queues[agent_id].add(q)
        return q

    def unregister(self, agent_id: int, q: asyncio.Queue) -> None:
        self.queues[agent_id].discard(q)

    def connected(self, agent_id: int) -> bool:
        return bool(self.queues.get(agent_id))

    def wake(self, agent_id: int, kind: str = "wake") -> None:
        """동기 코드(스레드풀)에서도 안전하게 호출 가능."""
        if not self.loop:
            return
        for q in list(self.queues.get(agent_id, ())):
            try:
                self.loop.call_soon_threadsafe(self._put, q, {"type": kind})
            except RuntimeError:
                pass

    @staticmethod
    def _put(q: asyncio.Queue, msg: dict) -> None:
        if not q.full():
            q.put_nowait(msg)


hub = Hub()
