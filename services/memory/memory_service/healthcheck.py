import os
import sys

import grpc

from engram_contracts.rpc import engram_pb2, engram_pb2_grpc


def main() -> None:
    target = os.environ.get("MEMORY_TARGET", "127.0.0.1:18413")
    channel = grpc.insecure_channel(target)
    stub = engram_pb2_grpc.MemoryStub(channel)
    response = stub.Check(engram_pb2.HealthRequest(), timeout=2)
    if response.status != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
