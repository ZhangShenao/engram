import uuid

from engram_queue import ack, claim, publish
from engram_queue.queue import init_db, nack


def test_publish_claim_ack_and_nack():
    init_db()
    topic = f"test.{uuid.uuid4()}"
    message_id = publish(topic, {"hello": "queue"})
    job = claim(topic)
    assert job is not None
    assert job["id"] == message_id
    assert job["payload"]["hello"] == "queue"
    assert claim(topic) is None
    nack(job["id"], job["attempts"])
    # The message stays, but it is not ready until the delay elapses.
    assert claim(topic) is None
    ack(message_id)
    assert claim(topic) is None
