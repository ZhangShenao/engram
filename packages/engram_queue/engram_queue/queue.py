"""Kafka-backed queue for memory extract, reinforce, and dead letters.

context-service publishes. memory-service consumes with manual offset commits.
A failed job is written back to the same topic with a later ``availableAtMs``.
After five attempts it is committed away and copied to ``memory.dead``.
"""

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError, for_code
from dotenv import load_dotenv

for _parent in Path(__file__).resolve().parents:
    _env_file = _parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file)
        break

logger = logging.getLogger("engram.queue")

TOPICS = ("memory.extract", "memory.reinforce")
DLQ_TOPIC = "memory.dead"
MAX_ATTEMPTS = 5
POLL_TIMEOUT_MS = 200

_LOCK = threading.Lock()
_LOOP: asyncio.AbstractEventLoop | None = None
_LOOP_THREAD: threading.Thread | None = None
_BROKER: "Broker | None" = None


def bootstrap_servers() -> str:
    return os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _LOOP, _LOOP_THREAD
    with _LOCK:
        if _LOOP is None:
            loop = asyncio.new_event_loop()

            def _run() -> None:
                asyncio.set_event_loop(loop)
                loop.run_forever()

            thread = threading.Thread(target=_run, name="engram-kafka", daemon=True)
            thread.start()
            _LOOP = loop
            _LOOP_THREAD = thread
        return _LOOP


def _submit(coro, timeout: float = 30):
    future = asyncio.run_coroutine_threadsafe(coro, _ensure_loop())
    return future.result(timeout=timeout)


@dataclass
class _Held:
    message_id: str
    topic: str
    partition: int
    offset: int
    payload: dict
    attempts: int
    available_at_ms: int
    inflight: bool = False


class Broker:
    def __init__(self) -> None:
        self._servers = bootstrap_servers()
        self._producer: AIOKafkaProducer | None = None
        self._consumer: AIOKafkaConsumer | None = None
        self._admin: AIOKafkaAdminClient | None = None
        self._created: set[str] = set()
        self._consume_topics: set[str] = set(TOPICS)
        self._held: dict[str, _Held] = {}

    async def aclose(self) -> None:
        await self._stop_consumer()
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None
        if self._admin is not None:
            await self._admin.close()
            self._admin = None
        self._created.clear()
        self._held.clear()

    async def ensure(self, topics: list[str]) -> None:
        missing = [name for name in topics if name not in self._created]
        if missing:
            await self._create(missing)
            self._created.update(missing)
        consume = {name for name in topics if name != DLQ_TOPIC}
        if self._consumer is not None and not consume <= self._consume_topics:
            await self._stop_consumer()
        self._consume_topics.update(consume)

    async def publish(self, topic: str, payload: dict) -> str:
        message_id = str(uuid.uuid4())
        await self.ensure([topic, *TOPICS, DLQ_TOPIC])
        await self._send(topic, payload, message_id, 0, _now_ms())
        return message_id

    async def claim(self, topic: str) -> dict | None:
        if topic not in self._consume_topics:
            self._consume_topics.add(topic)
            if self._consumer is not None:
                await self._stop_consumer()
        ready = self._lock_ready(topic)
        if ready is not None:
            return ready
        if any(item.topic == topic for item in self._held.values()):
            return None
        await self._poll()
        return self._lock_ready(topic)

    async def ack(self, message_id: str) -> None:
        held = self._held.get(message_id)
        if held is None:
            return
        await self._finish(held)

    async def nack(self, message_id: str, attempts: int) -> None:
        held = self._held.get(message_id)
        if held is None:
            return
        try:
            if attempts >= MAX_ATTEMPTS:
                logger.warning("dead-letter %s after %s attempts", message_id, attempts)
                await self._send(DLQ_TOPIC, held.payload, message_id, attempts, _now_ms())
            else:
                delay_ms = min(30, attempts * 2) * 1000
                await self._send(
                    held.topic,
                    held.payload,
                    message_id,
                    attempts,
                    _now_ms() + delay_ms,
                )
        except Exception:
            held.inflight = False
            raise
        await self._finish(held)

    async def _create(self, topics: list[str]) -> None:
        admin = await self._admin_client()
        present = set(await admin.list_topics())
        missing = [name for name in topics if name not in present]
        if not missing:
            return
        response = await admin.create_topics(
            [NewTopic(name=name, num_partitions=1, replication_factor=1) for name in missing],
            timeout_ms=15_000,
        )
        for item in response.topic_errors:
            code = int(item[1])
            if code == 0:
                continue
            err = for_code(code)
            if err is TopicAlreadyExistsError:
                continue
            detail = item[2] if len(item) > 2 and item[2] else ""
            raise err(f"Could not create topic {item[0]}: {detail}")

    async def _send(
        self,
        topic: str,
        payload: dict,
        message_id: str,
        attempts: int,
        available_at_ms: int,
    ) -> None:
        producer = await self._producer_client()
        body = json.dumps(
            {
                "id": message_id,
                "payload": payload,
                "attempts": attempts,
                "availableAtMs": available_at_ms,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        await producer.send_and_wait(topic, value=body, key=message_id.encode())

    async def _poll(self) -> None:
        consumer = await self._consumer_client()
        batches = await consumer.getmany(timeout_ms=POLL_TIMEOUT_MS, max_records=1)
        for tp, messages in batches.items():
            for msg in messages:
                if not await self._hold(consumer, tp, msg):
                    continue
                consumer.pause(tp)
                return

    async def _hold(self, consumer: AIOKafkaConsumer, tp: TopicPartition, msg) -> bool:
        try:
            body = json.loads(msg.value)
            payload = body["payload"]
            if not isinstance(payload, dict):
                raise TypeError("payload must be an object")
            held = _Held(
                message_id=str(body["id"]),
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
                payload=payload,
                attempts=int(body.get("attempts") or 0),
                available_at_ms=int(body.get("availableAtMs") or 0),
            )
        except (TypeError, ValueError, KeyError, UnicodeError, json.JSONDecodeError):
            logger.exception("dropping malformed record topic=%s offset=%s", msg.topic, msg.offset)
            await consumer.commit({tp: msg.offset + 1})
            return False
        self._held[held.message_id] = held
        return True

    def _lock_ready(self, topic: str) -> dict | None:
        now = _now_ms()
        for held in self._held.values():
            if held.topic != topic or held.inflight or held.available_at_ms > now:
                continue
            held.inflight = True
            held.attempts += 1
            return {
                "id": held.message_id,
                "topic": held.topic,
                "payload": held.payload,
                "attempts": held.attempts,
            }
        return None

    async def _finish(self, held: _Held) -> None:
        consumer = await self._consumer_client()
        tp = TopicPartition(held.topic, held.partition)
        try:
            await consumer.commit({tp: held.offset + 1})
        except Exception:
            held.inflight = False
            raise
        self._held.pop(held.message_id, None)
        if tp in consumer.paused():
            consumer.resume(tp)

    async def _producer_client(self) -> AIOKafkaProducer:
        if self._producer is None:
            producer = AIOKafkaProducer(
                bootstrap_servers=self._servers,
                client_id="engram",
                acks="all",
                enable_idempotence=True,
                request_timeout_ms=15_000,
            )
            await producer.start()
            self._producer = producer
        return self._producer

    async def _admin_client(self) -> AIOKafkaAdminClient:
        if self._admin is None:
            admin = AIOKafkaAdminClient(
                bootstrap_servers=self._servers,
                client_id="engram-admin",
            )
            await admin.start()
            self._admin = admin
        return self._admin

    async def _consumer_client(self) -> AIOKafkaConsumer:
        if self._consumer is None:
            topics = tuple(sorted(self._consume_topics))
            consumer = AIOKafkaConsumer(
                *topics,
                bootstrap_servers=self._servers,
                group_id=os.environ.get("KAFKA_GROUP_ID", "engram-memory"),
                client_id="engram-memory",
                enable_auto_commit=False,
                auto_offset_reset="earliest",
                max_poll_interval_ms=600_000,
                session_timeout_ms=10_000,
            )
            await consumer.start()
            deadline = time.monotonic() + 10
            while not consumer.assignment() and time.monotonic() < deadline:
                await asyncio.sleep(0.1)
            self._consumer = consumer
        return self._consumer

    async def _stop_consumer(self) -> None:
        consumer = self._consumer
        self._consumer = None
        self._held.clear()
        if consumer is not None:
            await consumer.stop()


def _broker() -> Broker:
    global _BROKER
    with _LOCK:
        if _BROKER is None:
            _BROKER = Broker()
        return _BROKER


def ensure_topics(extra: list[str] | None = None) -> None:
    names = [*TOPICS, DLQ_TOPIC, *(extra or [])]
    _submit(_broker().ensure(names))


def publish(topic: str, payload: dict) -> str:
    return _submit(_broker().publish(topic, payload))


def claim(topic: str) -> dict | None:
    return _submit(_broker().claim(topic))


def ack(message_id: str) -> None:
    _submit(_broker().ack(message_id))


def nack(message_id: str, attempts: int) -> None:
    _submit(_broker().nack(message_id, attempts))


def close() -> None:
    global _BROKER
    with _LOCK:
        broker = _BROKER
        _BROKER = None
    if broker is not None:
        _submit(broker.aclose())


async def _collect(topic: str, message_id: str, timeout: float) -> list[dict]:
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers(),
        group_id=f"engram-peek-{uuid.uuid4()}",
        client_id="engram-peek",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    try:
        found: list[dict] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            batches = await consumer.getmany(timeout_ms=300, max_records=50)
            for messages in batches.values():
                for msg in messages:
                    try:
                        body = json.loads(msg.value)
                    except (TypeError, ValueError, UnicodeError):
                        continue
                    if body.get("id") == message_id:
                        found.append(body)
            if found:
                return found
        return found
    finally:
        await consumer.stop()


def collect_records(topic: str, message_id: str, timeout: float = 8) -> list[dict]:
    return _submit(_collect(topic, message_id, timeout), timeout=timeout + 10)
