import asyncio
import time
import uuid

import pytest
from aiokafka import AIOKafkaProducer

from engram_queue.queue import (
    DLQ_TOPIC,
    MAX_ATTEMPTS,
    ack,
    bootstrap_servers,
    claim,
    close,
    collect_records,
    ensure_topics,
    nack,
    publish,
)


@pytest.fixture
def topic(monkeypatch):
    name = f"test.{uuid.uuid4()}"
    monkeypatch.setenv("KAFKA_GROUP_ID", f"engram-test-{uuid.uuid4()}")
    close()
    ensure_topics([name])
    yield name
    close()


def _wait_claim(name: str, timeout: float = 20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = claim(name)
        if job is not None:
            return job
        time.sleep(0.1)
    raise AssertionError(f"no message on {name}")


def test_publish_claim_ack_and_delayed_nack(topic):
    message_id = publish(topic, {"hello": "queue"})
    job = _wait_claim(topic)
    assert job["id"] == message_id
    assert job["payload"]["hello"] == "queue"
    assert job["attempts"] == 1
    assert claim(topic) is None

    nack(job["id"], job["attempts"])
    saw_held = False
    for _ in range(15):
        assert claim(topic) is None
        saw_held = True
        time.sleep(0.05)
    assert saw_held
    ack(message_id)
    assert claim(topic) is None
    ack(str(uuid.uuid4()))


def test_nack_redelivers_after_backoff(topic):
    message_id = publish(topic, {"hello": "retry"})
    job = _wait_claim(topic)
    nack(job["id"], job["attempts"])
    assert claim(topic) is None
    time.sleep(2.4)
    again = _wait_claim(topic)
    assert again["id"] == message_id
    assert again["attempts"] == 2
    ack(again["id"])
    assert claim(topic) is None


def test_malformed_record_is_skipped(topic):
    async def send_garbage() -> None:
        producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers())
        await producer.start()
        try:
            await producer.send_and_wait(topic, value=b"not-json")
        finally:
            await producer.stop()

    asyncio.run(send_garbage())
    message_id = publish(topic, {"hello": "after"})
    job = _wait_claim(topic)
    assert job["id"] == message_id
    assert job["payload"]["hello"] == "after"
    ack(job["id"])


def test_nack_at_max_attempts_dead_letters(topic):
    message_id = publish(topic, {"hello": "dead"})
    job = _wait_claim(topic)
    nack(job["id"], MAX_ATTEMPTS)
    assert claim(topic) is None
    letters = collect_records(DLQ_TOPIC, message_id)
    assert letters
    assert letters[0]["payload"]["hello"] == "dead"
    assert letters[0]["attempts"] == MAX_ATTEMPTS
